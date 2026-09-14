"""
Shared configuration settings for VirtualPyTest services.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    """Database configuration"""
    url: Optional[str] = None
    host: str = "localhost"
    port: int = 5432
    name: str = "virtualpytest"
    user: str = "virtualpytest"
    password: str = ""

@dataclass
class ServiceConfig:
    """Service-specific configuration"""
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    environment: str = "development"

@dataclass
class SecurityConfig:
    """Security and authentication configuration"""
    secret_key: str = os.getenv('SECRET_KEY', 'dev-secret-key')
    jwt_secret: str = os.getenv('JWT_SECRET', 'jwt-secret-key')
    cors_origins: list = None

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = ["http://localhost:3000", "http://localhost:5173"]

@dataclass
class SharedConfig:
    """Main shared configuration"""
    database: DatabaseConfig
    security: SecurityConfig
    
    # Default team and user IDs
    default_team_id: str = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
    default_user_id: str = "default-user"
    
    @classmethod
    def from_env(cls, service_name: str = "virtualpytest") -> 'SharedConfig':
        """Create configuration from environment variables"""
        database = DatabaseConfig(
            url=os.getenv('DATABASE_URL'),
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', '5432')),
            name=os.getenv('DB_NAME', 'virtualpytest'),
            user=os.getenv('DB_USER', 'virtualpytest'),
            password=os.getenv('DB_PASSWORD', '')
        )
        
        security = SecurityConfig()
        
        return cls(
            database=database,
            security=security
        )

# Global shared configuration instance
shared_config = SharedConfig.from_env() 