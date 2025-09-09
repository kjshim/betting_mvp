#!/bin/bash

# GCP Deployment Script for Betting MVP
# This script automates the deployment process to Google Cloud Platform

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
PROJECT_ID=""
REGION="us-central1"
SERVICE_NAME="betting-mvp-api"
DATABASE_INSTANCE="betting-mvp-db"
REDIS_INSTANCE="betting-mvp-redis"

# Function to check if gcloud is installed and authenticated
check_gcloud() {
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n 1 &> /dev/null; then
        log_error "Not authenticated with gcloud. Run 'gcloud auth login'"
        exit 1
    fi
    
    log_success "gcloud is installed and authenticated"
}

# Function to get or set project ID
setup_project() {
    if [ -z "$PROJECT_ID" ]; then
        CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
        if [ -z "$CURRENT_PROJECT" ]; then
            read -p "Enter your GCP Project ID: " PROJECT_ID
            gcloud config set project $PROJECT_ID
        else
            PROJECT_ID=$CURRENT_PROJECT
        fi
    fi
    
    log_info "Using project: $PROJECT_ID"
    
    # Verify project exists
    if ! gcloud projects describe $PROJECT_ID &>/dev/null; then
        log_error "Project $PROJECT_ID does not exist or you don't have access"
        exit 1
    fi
    
    log_success "Project verified"
}

# Function to enable required APIs
enable_apis() {
    log_info "Enabling required APIs..."
    
    gcloud services enable \
        cloudbuild.googleapis.com \
        run.googleapis.com \
        sql-admin.googleapis.com \
        sqladmin.googleapis.com \
        redis.googleapis.com \
        secretmanager.googleapis.com \
        cloudresourcemanager.googleapis.com \
        compute.googleapis.com \
        container.googleapis.com \
        logging.googleapis.com \
        monitoring.googleapis.com \
        --project=$PROJECT_ID
    
    log_success "APIs enabled"
}

# Function to create Cloud SQL database
setup_database() {
    log_info "Setting up Cloud SQL database..."
    
    # Check if instance exists
    if gcloud sql instances describe $DATABASE_INSTANCE --project=$PROJECT_ID &>/dev/null; then
        log_warning "Cloud SQL instance $DATABASE_INSTANCE already exists"
    else
        log_info "Creating Cloud SQL instance..."
        
        # Get database password
        read -s -p "Enter database root password: " DB_ROOT_PASSWORD
        echo
        read -s -p "Enter application database password: " DB_APP_PASSWORD
        echo
        
        gcloud sql instances create $DATABASE_INSTANCE \
            --database-version=POSTGRES_15 \
            --tier=db-f1-micro \
            --region=$REGION \
            --root-password=$DB_ROOT_PASSWORD \
            --storage-type=SSD \
            --storage-size=10GB \
            --backup-start-time=03:00 \
            --project=$PROJECT_ID
        
        log_info "Creating database..."
        gcloud sql databases create betting_mvp --instance=$DATABASE_INSTANCE --project=$PROJECT_ID
        
        log_info "Creating application user..."
        gcloud sql users create appuser \
            --instance=$DATABASE_INSTANCE \
            --password=$DB_APP_PASSWORD \
            --project=$PROJECT_ID
        
        log_success "Cloud SQL setup completed"
        
        # Store database URL in Secret Manager
        INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe $DATABASE_INSTANCE --project=$PROJECT_ID --format="value(connectionName)")
        DATABASE_URL="postgresql+psycopg://appuser:$DB_APP_PASSWORD@/betting_mvp?host=/cloudsql/$INSTANCE_CONNECTION_NAME"
        echo "$DATABASE_URL" | gcloud secrets create database-url --data-file=- --project=$PROJECT_ID
    fi
}

# Function to create Redis instance
setup_redis() {
    log_info "Setting up Redis instance..."
    
    # Check if instance exists
    if gcloud redis instances describe $REDIS_INSTANCE --region=$REGION --project=$PROJECT_ID &>/dev/null; then
        log_warning "Redis instance $REDIS_INSTANCE already exists"
    else
        log_info "Creating Redis instance..."
        
        gcloud redis instances create $REDIS_INSTANCE \
            --size=1 \
            --region=$REGION \
            --redis-version=redis_6_x \
            --tier=basic \
            --project=$PROJECT_ID
        
        log_success "Redis setup completed"
    fi
    
    # Get Redis connection info and store in secrets
    REDIS_INFO=$(gcloud redis instances describe $REDIS_INSTANCE --region=$REGION --project=$PROJECT_ID --format="value(host,port)")
    REDIS_HOST=$(echo $REDIS_INFO | cut -d' ' -f1)
    REDIS_PORT=$(echo $REDIS_INFO | cut -d' ' -f2)
    REDIS_URL="redis://$REDIS_HOST:$REDIS_PORT/0"
    
    echo "$REDIS_URL" | gcloud secrets create redis-url --data-file=- --project=$PROJECT_ID || \
    echo "$REDIS_URL" | gcloud secrets versions add redis-url --data-file=- --project=$PROJECT_ID
}

# Function to create secrets
setup_secrets() {
    log_info "Setting up secrets..."
    
    # Generate secrets if they don't exist
    create_secret_if_not_exists() {
        local secret_name=$1
        local secret_value=$2
        
        if ! gcloud secrets describe $secret_name --project=$PROJECT_ID &>/dev/null; then
            echo "$secret_value" | gcloud secrets create $secret_name --data-file=- --project=$PROJECT_ID
            log_info "Created secret: $secret_name"
        else
            log_warning "Secret $secret_name already exists"
        fi
    }
    
    # JWT Secret
    JWT_SECRET=$(openssl rand -hex 32)
    create_secret_if_not_exists "jwt-secret" "$JWT_SECRET"
    
    # Session Secret
    SESSION_SECRET=$(openssl rand -hex 32)
    create_secret_if_not_exists "session-secret" "$SESSION_SECRET"
    
    # Admin Password
    create_secret_if_not_exists "admin-password" "admin2024!"
    
    # Solana Derive Seed
    SOLANA_SEED=$(openssl rand -hex 32)
    create_secret_if_not_exists "solana-derive-seed" "$SOLANA_SEED"
    
    # Grant access to compute service account
    PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
    SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
    
    for secret in "database-url" "jwt-secret" "session-secret" "admin-password" "solana-derive-seed" "redis-url"; do
        gcloud secrets add-iam-policy-binding $secret \
            --member="serviceAccount:$SERVICE_ACCOUNT" \
            --role="roles/secretmanager.secretAccessor" \
            --project=$PROJECT_ID
    done
    
    log_success "Secrets setup completed"
}

# Function to build and deploy application
deploy_app() {
    log_info "Building and deploying application..."
    
    # Submit build to Cloud Build
    gcloud builds submit --config cloudbuild.yaml --project=$PROJECT_ID .
    
    log_success "Application deployed successfully"
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
    log_success "Application URL: $SERVICE_URL"
}

# Function to run database migrations
run_migrations() {
    log_info "Running database migrations..."
    
    # Create migration job
    if ! gcloud run jobs describe betting-mvp-migrate --region=$REGION --project=$PROJECT_ID &>/dev/null; then
        INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe $DATABASE_INSTANCE --project=$PROJECT_ID --format="value(connectionName)")
        
        gcloud run jobs create betting-mvp-migrate \
            --image=gcr.io/$PROJECT_ID/betting-mvp:latest \
            --region=$REGION \
            --add-cloudsql-instances=$INSTANCE_CONNECTION_NAME \
            --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
            --command=alembic \
            --args=upgrade,head \
            --project=$PROJECT_ID
    fi
    
    # Execute migration
    gcloud run jobs execute betting-mvp-migrate --region=$REGION --project=$PROJECT_ID --wait
    
    log_success "Database migrations completed"
}

# Function to setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."
    
    # Create uptime check
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
    
    # Note: This requires alpha component
    if gcloud components list --filter="id:alpha" --format="value(state.name)" | grep -q "Installed"; then
        gcloud alpha monitoring uptime-checks create \
            --display-name="Betting MVP API Health Check" \
            --uri="$SERVICE_URL/health" \
            --project=$PROJECT_ID || log_warning "Failed to create uptime check"
    else
        log_warning "Alpha component not installed. Skipping uptime check creation."
        log_info "You can manually create uptime checks in the Cloud Console"
    fi
    
    log_success "Basic monitoring setup completed"
}

# Function to display deployment summary
display_summary() {
    log_success "==================================="
    log_success "DEPLOYMENT COMPLETED SUCCESSFULLY!"
    log_success "==================================="
    
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
    
    echo ""
    log_info "Application Details:"
    echo "  • Project ID: $PROJECT_ID"
    echo "  • Service URL: $SERVICE_URL"
    echo "  • Region: $REGION"
    echo "  • Database: $DATABASE_INSTANCE"
    echo "  • Redis: $REDIS_INSTANCE"
    echo ""
    log_info "Next Steps:"
    echo "  1. Visit $SERVICE_URL to test your application"
    echo "  2. Set up custom domain (optional): https://cloud.google.com/run/docs/mapping-custom-domains"
    echo "  3. Configure monitoring: https://console.cloud.google.com/monitoring"
    echo "  4. Review logs: gcloud run logs tail $SERVICE_NAME --region=$REGION"
    echo ""
    log_info "Estimated monthly cost: ~\$90-120 USD"
}

# Main deployment flow
main() {
    log_info "Starting GCP deployment for Betting MVP..."
    echo ""
    
    # Check prerequisites
    check_gcloud
    setup_project
    
    # Ask for confirmation
    echo ""
    log_warning "This will create the following resources in project '$PROJECT_ID':"
    echo "  • Cloud SQL PostgreSQL instance (~\$25/month)"
    echo "  • Redis instance (~\$45/month)"
    echo "  • Cloud Run service (~\$20-50/month)"
    echo "  • Secret Manager secrets"
    echo ""
    read -p "Continue with deployment? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Deployment cancelled"
        exit 0
    fi
    
    # Execute deployment steps
    enable_apis
    setup_database
    setup_redis
    setup_secrets
    deploy_app
    run_migrations
    setup_monitoring
    display_summary
}

# Handle script arguments
case "${1:-}" in
    "help" | "-h" | "--help")
        echo "GCP Deployment Script for Betting MVP"
        echo ""
        echo "Usage: $0 [COMMAND]"
        echo ""
        echo "Commands:"
        echo "  help    Show this help message"
        echo "  deploy  Start full deployment (default)"
        echo ""
        echo "Environment Variables:"
        echo "  PROJECT_ID    GCP Project ID (will prompt if not set)"
        echo "  REGION        GCP Region (default: us-central1)"
        echo ""
        exit 0
        ;;
    "deploy" | "")
        main
        ;;
    *)
        log_error "Unknown command: $1"
        echo "Run '$0 help' for usage information"
        exit 1
        ;;
esac