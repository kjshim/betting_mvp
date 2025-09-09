# GCP Deployment Guide for Betting MVP

This guide will walk you through deploying the Betting MVP application to Google Cloud Platform using Cloud Run, Cloud SQL, and Memorystore.

## Prerequisites

1. **Google Cloud Account** with billing enabled
2. **gcloud CLI** installed locally
3. **Docker** installed locally
4. **Domain name** (optional, for custom domain)

## Architecture Overview

```
Internet → Cloud Load Balancer → Cloud Run (API)
                                     ↓
                              Cloud SQL (PostgreSQL)
                                     ↓
                              Memorystore (Redis)
```

## Step 1: Initial GCP Setup

### 1.1 Install and Configure gcloud CLI

```bash
# Install gcloud CLI (if not already installed)
# Visit: https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login

# Set your project (create one if needed)
export PROJECT_ID="betting-mvp-prod"  # Change this to your desired project ID
gcloud projects create $PROJECT_ID
gcloud config set project $PROJECT_ID

# Enable billing (required)
# Go to: https://console.cloud.google.com/billing
```

### 1.2 Enable Required APIs

```bash
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    sql-admin.googleapis.com \
    sqladmin.googleapis.com \
    redis.googleapis.com \
    secretmanager.googleapis.com \
    cloudresourcemanager.googleapis.com \
    compute.googleapis.com \
    container.googleapis.com
```

## Step 2: Database Setup (Cloud SQL)

### 2.1 Create PostgreSQL Instance

```bash
# Create Cloud SQL PostgreSQL instance
gcloud sql instances create betting-mvp-db \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region=us-central1 \
    --root-password=YOUR_STRONG_PASSWORD_HERE \
    --storage-type=SSD \
    --storage-size=10GB \
    --backup-start-time=03:00

# Create database
gcloud sql databases create betting_mvp --instance=betting-mvp-db

# Create application user
gcloud sql users create appuser \
    --instance=betting-mvp-db \
    --password=YOUR_APP_PASSWORD_HERE
```

### 2.2 Get Database Connection Details

```bash
# Get instance connection name
gcloud sql instances describe betting-mvp-db --format="value(connectionName)"

# This will output something like: PROJECT_ID:REGION:betting-mvp-db
```

## Step 3: Redis Setup (Memorystore)

### 3.1 Create Redis Instance

```bash
# Create Memorystore Redis instance
gcloud redis instances create betting-mvp-redis \
    --size=1 \
    --region=us-central1 \
    --redis-version=redis_6_x \
    --tier=basic
```

### 3.2 Get Redis Connection Details

```bash
# Get Redis host and port
gcloud redis instances describe betting-mvp-redis \
    --region=us-central1 \
    --format="value(host,port)"
```

## Step 4: Secret Management

### 4.1 Create Secrets

```bash
# Database URL
echo "postgresql+psycopg://appuser:YOUR_APP_PASSWORD_HERE@/betting_mvp?host=/cloudsql/PROJECT_ID:us-central1:betting-mvp-db" | \
    gcloud secrets create database-url --data-file=-

# JWT Secret
openssl rand -hex 32 | gcloud secrets create jwt-secret --data-file=-

# Session Secret  
openssl rand -hex 32 | gcloud secrets create session-secret --data-file=-

# Admin Password
echo "admin2024!" | gcloud secrets create admin-password --data-file=-

# Solana Derive Seed
openssl rand -hex 32 | gcloud secrets create solana-derive-seed --data-file=-

# Redis URL (replace REDIS_HOST with actual host from previous step)
echo "redis://REDIS_HOST:6379/0" | gcloud secrets create redis-url --data-file=-
```

### 4.2 Grant Secret Access

```bash
# Grant Cloud Run service account access to secrets
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

gcloud secrets add-iam-policy-binding database-url \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding jwt-secret \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding session-secret \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding admin-password \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding solana-derive-seed \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding redis-url \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

## Step 5: Application Configuration

### 5.1 Create Production Dockerfile

Create `Dockerfile.prod`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Cloud SQL Proxy
RUN wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
RUN chmod +x cloud_sql_proxy

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8080

# Start command
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 5.2 Create Production Requirements

Update `requirements.txt` to include Cloud SQL connector:

```text
# Add to existing requirements.txt
cloud-sql-python-connector[pg8000]>=1.4.0
```

### 5.3 Update Settings for Production

Create `infra/settings_prod.py`:

```python
import os
from google.cloud import secretmanager
from pydantic import Field
from pydantic_settings import BaseSettings

def get_secret(secret_id: str, project_id: str) -> str:
    """Get secret from Google Secret Manager"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Error getting secret {secret_id}: {e}")
        return ""

class ProductionSettings(BaseSettings):
    # Get project ID from metadata server
    project_id: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    
    # Database
    database_url: str = Field(default="")
    
    # Redis
    redis_url: str = Field(default="")
    
    # Application settings
    timezone: str = Field(default="America/New_York")
    fee_bps: int = Field(default=100, ge=0, le=10000)
    settle_grace_min: int = Field(default=30, ge=1)
    close_fetch_delay_min: int = Field(default=5, ge=1)
    
    # Authentication
    jwt_secret: str = Field(default="")
    session_secret: str = Field(default="")
    admin_password: str = Field(default="")
    argon2_memory_cost: int = Field(default=65536)

    # Solana configuration
    solana_rpc_url: str = Field(default="https://api.mainnet-beta.solana.com")
    solana_usdc_mint: str = Field(default="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    solana_min_conf: int = Field(default=15)  # Higher for mainnet
    solana_derive_seed: str = Field(default="")

    def __post_init__(self):
        """Load secrets from Secret Manager"""
        if self.project_id:
            self.database_url = get_secret("database-url", self.project_id)
            self.redis_url = get_secret("redis-url", self.project_id)
            self.jwt_secret = get_secret("jwt-secret", self.project_id)
            self.session_secret = get_secret("session-secret", self.project_id)
            self.admin_password = get_secret("admin-password", self.project_id)
            self.solana_derive_seed = get_secret("solana-derive-seed", self.project_id)

    class Config:
        env_file = ".env"

# Use production settings in Cloud Run
settings = ProductionSettings()
```

## Step 6: Build and Deploy

### 6.1 Create Cloud Build Configuration

Create `cloudbuild.yaml`:

```yaml
steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: [
      'build',
      '-f', 'Dockerfile.prod',
      '-t', 'gcr.io/$PROJECT_ID/betting-mvp:$COMMIT_SHA',
      '-t', 'gcr.io/$PROJECT_ID/betting-mvp:latest',
      '.'
    ]
  
  # Push the container image to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/betting-mvp:$COMMIT_SHA']
  
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/betting-mvp:latest']
  
  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'gcloud'
    args: [
      'run', 'deploy', 'betting-mvp-api',
      '--image', 'gcr.io/$PROJECT_ID/betting-mvp:$COMMIT_SHA',
      '--platform', 'managed',
      '--region', 'us-central1',
      '--allow-unauthenticated',
      '--port', '8080',
      '--memory', '1Gi',
      '--cpu', '1',
      '--min-instances', '1',
      '--max-instances', '10',
      '--add-cloudsql-instances', '$PROJECT_ID:us-central1:betting-mvp-db',
      '--set-env-vars', 'GOOGLE_CLOUD_PROJECT=$PROJECT_ID',
      '--set-env-vars', 'ENVIRONMENT=production'
    ]

options:
  logging: CLOUD_LOGGING_ONLY

images:
  - 'gcr.io/$PROJECT_ID/betting-mvp:$COMMIT_SHA'
  - 'gcr.io/$PROJECT_ID/betting-mvp:latest'
```

### 6.2 Deploy with Cloud Build

```bash
# Submit build
gcloud builds submit --config cloudbuild.yaml .
```

## Step 7: Database Migrations

### 7.1 Run Migrations via Cloud Run Jobs

```bash
# Create a migration job
gcloud run jobs create betting-mvp-migrate \
    --image=gcr.io/$PROJECT_ID/betting-mvp:latest \
    --region=us-central1 \
    --add-cloudsql-instances=$PROJECT_ID:us-central1:betting-mvp-db \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
    --command=alembic \
    --args=upgrade,head

# Execute migration
gcloud run jobs execute betting-mvp-migrate --region=us-central1
```

## Step 8: Domain Setup (Optional)

### 8.1 Custom Domain

```bash
# Map custom domain
gcloud run domain-mappings create \
    --service=betting-mvp-api \
    --domain=yourdomain.com \
    --region=us-central1

# Follow the DNS configuration instructions provided
```

## Step 9: Monitoring & Logging

### 9.1 Set up Alerts

```bash
# Create uptime check
gcloud alpha monitoring uptime-checks create \
    --display-name="Betting MVP API" \
    --uri="https://betting-mvp-api-xxxxxxxxxx-uc.a.run.app/health"
```

## Step 10: Security & Optimization

### 10.1 Enable Container Analysis

```bash
gcloud services enable containeranalysis.googleapis.com
```

### 10.2 Set up IAM

```bash
# Create a custom service account for the application
gcloud iam service-accounts create betting-mvp-app \
    --display-name="Betting MVP Application"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:betting-mvp-app@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/cloudsql.client"

# Update Cloud Run to use custom service account
gcloud run services update betting-mvp-api \
    --service-account=betting-mvp-app@$PROJECT_ID.iam.gserviceaccount.com \
    --region=us-central1
```

## Cost Optimization

### Estimated Monthly Costs (us-central1):
- **Cloud Run**: ~$20-50/month (depends on traffic)
- **Cloud SQL (f1-micro)**: ~$25/month
- **Memorystore Redis (1GB Basic)**: ~$45/month
- **Total**: ~$90-120/month

### Cost Optimization Tips:
1. Use preemptible instances for non-critical workloads
2. Set up budget alerts
3. Use Cloud Scheduler to scale down during low-traffic hours
4. Monitor and optimize container resource usage

## Troubleshooting

### Common Issues:

1. **Database Connection Issues**
   - Verify Cloud SQL instance is running
   - Check database URL secret is correct
   - Ensure Cloud Run has Cloud SQL instances configured

2. **Secret Access Issues**
   - Verify service account has Secret Manager access
   - Check secret names match exactly

3. **Build Issues**
   - Verify all APIs are enabled
   - Check Dockerfile syntax
   - Ensure requirements.txt is complete

### Useful Commands:

```bash
# View logs
gcloud run services logs tail betting-mvp-api --region=us-central1

# Get service URL
gcloud run services describe betting-mvp-api --region=us-central1 --format="value(status.url)"

# View secrets
gcloud secrets versions list database-url
```

## Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_CLOUD_PROJECT` | GCP Project ID | `betting-mvp-prod` |
| `ENVIRONMENT` | Environment name | `production` |
| `DATABASE_URL` | PostgreSQL connection | From Secret Manager |
| `REDIS_URL` | Redis connection | From Secret Manager |

## Security Considerations

1. **Never commit secrets** to version control
2. **Use least privilege** IAM principles
3. **Enable audit logging** for all services
4. **Regularly update dependencies**
5. **Use VPC** for additional network security
6. **Enable DDoS protection** through Cloud Armor

---

## Quick Deployment Script

For convenience, here's a script to automate most of the deployment:

```bash
#!/bin/bash
# See deploy.sh in the scripts directory
```

This completes the GCP deployment setup. The application will be accessible via the Cloud Run URL and can handle production traffic with automatic scaling.