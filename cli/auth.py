import uuid
from datetime import datetime
from typing import Optional

import typer
from sqlalchemy import select
from rich.console import Console
from rich.table import Table

from api.auth import ApiKey, ApiKeyAuth, ApiKeyRole
from infra.db import SessionLocal

console = Console()
app = typer.Typer(help="API Key management commands")


@app.command()
def create_key(
    name: str = typer.Option(..., help="Human-readable name for the key"),
    role: ApiKeyRole = typer.Option(..., help="Role: user, admin, or readonly"),
    user_id: Optional[str] = typer.Option(None, help="User ID for user-level keys")
):
    """Create a new API key"""
    with SessionLocal() as db:
        try:
            # Generate new key
            api_key = ApiKeyAuth.generate_api_key()
            key_hash = ApiKeyAuth.hash_key(api_key)
            
            # Parse user_id if provided
            parsed_user_id = None
            if user_id:
                try:
                    parsed_user_id = uuid.UUID(user_id)
                except ValueError:
                    typer.echo(f"✗ Invalid user ID format: {user_id}", err=True)
                    raise typer.Exit(1)
            
            # Create database record
            api_key_record = ApiKey(
                key_hash=key_hash,
                name=name,
                role=role.value,
                user_id=parsed_user_id
            )
            
            db.add(api_key_record)
            db.commit()
            
            # Display the key (only time it's shown in plain text)
            console.print("✅ API Key Created Successfully!", style="bold green")
            console.print(f"📝 Name: {name}")
            console.print(f"🔑 Role: {role.value}")
            if user_id:
                console.print(f"👤 User ID: {user_id}")
            console.print(f"🆔 Key ID: {api_key_record.id}")
            console.print("\n🔐 API Key (save this - it won't be shown again):")
            console.print(f"[bold red]{api_key}[/bold red]")
            console.print("\n💡 Usage: Include in Authorization header as 'Bearer {key}'")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create API key: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def list_keys():
    """List all API keys"""
    with SessionLocal() as db:
        try:
            result = db.execute(
                select(ApiKey).order_by(ApiKey.created_at.desc())
            )
            keys = result.scalars().all()
            
            if not keys:
                console.print("No API keys found.", style="yellow")
                return
            
            table = Table(title="API Keys")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Role", style="green")
            table.add_column("User ID", style="blue")
            table.add_column("Active", style="yellow")
            table.add_column("Created", style="dim")
            table.add_column("Last Used", style="dim")
            
            for key in keys:
                last_used = key.last_used.strftime("%Y-%m-%d %H:%M") if key.last_used else "Never"
                created = key.created_at.strftime("%Y-%m-%d %H:%M")
                user_id_str = str(key.user_id)[:8] + "..." if key.user_id else "-"
                
                table.add_row(
                    str(key.id)[:8] + "...",
                    key.name,
                    key.role,
                    user_id_str,
                    "✅" if key.is_active == "true" else "❌",
                    created,
                    last_used
                )
            
            console.print(table)
            
        except Exception as e:
            typer.echo(f"✗ Failed to list API keys: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def revoke_key(
    key_id: str = typer.Option(..., help="API Key ID to revoke")
):
    """Revoke an API key"""
    with SessionLocal() as db:
        try:
            # Find the key
            result = db.execute(
                select(ApiKey).where(ApiKey.id == key_id)
            )
            api_key = result.scalar_one_or_none()
            
            if not api_key:
                typer.echo(f"✗ API key not found: {key_id}", err=True)
                raise typer.Exit(1)
            
            # Confirm revocation
            if not typer.confirm(f"Revoke API key '{api_key.name}' ({api_key.role})?"):
                typer.echo("Operation cancelled.")
                return
            
            # Revoke the key
            api_key.is_active = "false"
            db.commit()
            
            console.print(f"✅ API key '{api_key.name}' has been revoked.", style="bold green")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to revoke API key: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def test_key(
    api_key: str = typer.Option(..., help="API key to test")
):
    """Test an API key"""
    try:
        import requests
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        # Test health endpoint (should work for all keys)
        response = requests.get("http://localhost:8000/health", headers=headers)
        
        if response.status_code == 200:
            console.print("✅ API key is valid and working!", style="bold green")
        else:
            console.print(f"❌ API key test failed: {response.status_code}", style="bold red")
            console.print(response.text)
            
    except requests.exceptions.ConnectionError:
        console.print("❌ Could not connect to API server. Make sure it's running.", style="bold red")
    except Exception as e:
        console.print(f"❌ Error testing API key: {e}", style="bold red")


@app.command()
def rotate_key(
    key_id: str = typer.Option(..., help="API Key ID to rotate")
):
    """Rotate an API key (generate new key, keep same permissions)"""
    with SessionLocal() as db:
        try:
            # Find the existing key
            result = db.execute(
                select(ApiKey).where(ApiKey.id == key_id)
            )
            old_key = result.scalar_one_or_none()
            
            if not old_key:
                typer.echo(f"✗ API key not found: {key_id}", err=True)
                raise typer.Exit(1)
            
            if old_key.is_active != "true":
                typer.echo("✗ Cannot rotate an inactive key", err=True)
                raise typer.Exit(1)
            
            # Generate new key
            new_api_key = ApiKeyAuth.generate_api_key()
            new_key_hash = ApiKeyAuth.hash_key(new_api_key)
            
            # Update the record
            old_key.key_hash = new_key_hash
            old_key.last_used = None  # Reset usage tracking
            
            db.commit()
            
            console.print("✅ API Key Rotated Successfully!", style="bold green")
            console.print(f"📝 Name: {old_key.name}")
            console.print(f"🔑 Role: {old_key.role}")
            console.print(f"🆔 Key ID: {old_key.id}")
            console.print("\n🔐 New API Key (save this - it won't be shown again):")
            console.print(f"[bold red]{new_api_key}[/bold red]")
            console.print("\n⚠️  Update all applications using the old key!")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to rotate API key: {e}", err=True)
            raise typer.Exit(1)


if __name__ == "__main__":
    app()