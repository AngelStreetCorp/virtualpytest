# Shared Library Technical Documentation

**Common utilities and configuration shared across all Python services.**

---

## 🎯 **Purpose**

Shared Library provides:
- **Configuration Management**: Environment-based settings
- **Data Models**: Common data structures
- **Utility Functions**: Helper functions and validators
- **Constants**: System-wide constants
- **Exception Handling**: Custom exception classes

---

## 📁 **Structure**

```
shared/lib/
├── config/
│   ├── settings.py          # Main configuration classes
│   ├── environments.py      # Environment-specific configs
│   └── devices/             # Device configuration files
├── models/
│   ├── device.py           # Device data models
│   ├── test_case.py        # Test case models
│   └── execution.py        # Execution models
├── utils/
│   ├── validators.py       # Input validation
│   ├── constants.py        # System constants
│   ├── exceptions.py       # Custom exceptions
│   ├── logging_config.py   # Logging setup
│   └── helpers.py          # General utilities
└── __init__.py
```

---

## ⚙️ **Configuration System**

### Main Configuration Class
```python
import os
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    url: str
    host: str
    port: int
    name: str
    user: str
    password: str

@dataclass
class SecurityConfig:
    secret_key: str
    jwt_secret: str
    cors_origins: List[str]

@dataclass
class ExternalServicesConfig:
    supabase_url: str
    supabase_anon_key: str
    openrouter_api_key: Optional[str]
    cloudflare_r2_endpoint: Optional[str]
    cloudflare_r2_access_key: Optional[str]
    cloudflare_r2_secret_key: Optional[str]

class SharedConfig:
    def __init__(self):
        self.database = self._load_database_config()
        self.security = self._load_security_config()
        self.external_services = self._load_external_services_config()
        
    def _load_database_config(self) -> DatabaseConfig:
        return DatabaseConfig(
            url=os.environ.get('DATABASE_URL', ''),
            host=os.environ.get('DB_HOST', 'localhost'),
            port=int(os.environ.get('DB_PORT', 5432)),
            name=os.environ.get('DB_NAME', 'virtualpytest'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', '')
        )
    
    def _load_security_config(self) -> SecurityConfig:
        return SecurityConfig(
            secret_key=os.environ.get('SECRET_KEY', 'dev-secret-key'),
            jwt_secret=os.environ.get('JWT_SECRET', 'jwt-secret'),
            cors_origins=os.environ.get('CORS_ORIGINS', '').split(',')
        )
    
    def _load_external_services_config(self) -> ExternalServicesConfig:
        return ExternalServicesConfig(
            supabase_url=os.environ.get('SUPABASE_URL', ''),
            supabase_anon_key=os.environ.get('SUPABASE_ANON_KEY', ''),
            openrouter_api_key=os.environ.get('OPENROUTER_API_KEY'),
            cloudflare_r2_endpoint=os.environ.get('CLOUDFLARE_R2_ENDPOINT'),
            cloudflare_r2_access_key=os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID'),
            cloudflare_r2_secret_key=os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
        )

# Global configuration instance
shared_config = SharedConfig()
```

### Environment-Specific Configuration
```python
import os
from enum import Enum

class Environment(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class EnvironmentConfig:
    def __init__(self):
        self.environment = Environment(
            os.environ.get('ENVIRONMENT', 'development')
        )
        
    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT
    
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION
    
    def get_log_level(self) -> str:
        if self.is_development:
            return 'DEBUG'
        elif self.environment == Environment.STAGING:
            return 'INFO'
        else:
            return 'WARNING'
    
    def get_database_pool_size(self) -> int:
        if self.is_development:
            return 5
        elif self.environment == Environment.STAGING:
            return 10
        else:
            return 20
```

---

## 📊 **Data Models**

### Device Models
```python
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime

class DeviceStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"

class DeviceType(Enum):
    ANDROID_MOBILE = "android_mobile"
    ANDROID_TV = "android_tv"
    IOS_MOBILE = "ios_mobile"
    STB = "stb"
    SMART_TV = "smart_tv"
    DESKTOP = "desktop"

@dataclass
class Device:
    id: str
    name: str
    device_type: DeviceType
    model: str
    host_id: str
    status: DeviceStatus
    capabilities: List[str]
    configuration: Dict[str, Any]
    last_seen: datetime
    created_at: datetime
    updated_at: datetime
    
    def is_available(self) -> bool:
        return self.status == DeviceStatus.ONLINE
    
    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'device_type': self.device_type.value,
            'model': self.model,
            'host_id': self.host_id,
            'status': self.status.value,
            'capabilities': self.capabilities,
            'configuration': self.configuration,
            'last_seen': self.last_seen.isoformat(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
```

### Test Case Models
```python
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class TestStep:
    id: str
    action: str
    parameters: Dict[str, Any]
    expected_result: Optional[str] = None
    verification_config: Optional[Dict[str, Any]] = None
    timeout: int = 30
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'action': self.action,
            'parameters': self.parameters,
            'expected_result': self.expected_result,
            'verification_config': self.verification_config,
            'timeout': self.timeout
        }

@dataclass
class TestCase:
    id: str
    name: str
    description: str
    device_model: str
    steps: List[TestStep]
    tags: List[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    
    def get_step_count(self) -> int:
        return len(self.steps)
    
    def get_estimated_duration(self) -> int:
        """Estimate duration in seconds based on steps"""
        return sum(step.timeout for step in self.steps)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'device_model': self.device_model,
            'steps': [step.to_dict() for step in self.steps],
            'tags': self.tags,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
```

---

## 🔧 **Utility Functions**

### Validation Utilities
```python
import re
from typing import Any, List, Dict, Optional
from email_validator import validate_email as _validate_email

class ValidationError(Exception):
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(message)

def validate_email(email: str) -> bool:
    """Validate email address format"""
    try:
        _validate_email(email)
        return True
    except:
        return False

def validate_device_id(device_id: str) -> bool:
    """Validate device ID format"""
    pattern = r'^[a-zA-Z0-9_-]+$'
    return bool(re.match(pattern, device_id)) and len(device_id) <= 50

def validate_test_case_name(name: str) -> bool:
    """Validate test case name"""
    return isinstance(name, str) and 1 <= len(name.strip()) <= 100

def validate_json_config(config: Any) -> Dict[str, Any]:
    """Validate and normalize JSON configuration"""
    if not isinstance(config, dict):
        raise ValidationError("Configuration must be a dictionary")
    
    # Remove null values
    cleaned_config = {k: v for k, v in config.items() if v is not None}
    
    return cleaned_config

def validate_host_url(url: str) -> bool:
    """Validate host URL format"""
    pattern = r'^https?://[a-zA-Z0-9.-]+(:[0-9]+)?$'
    return bool(re.match(pattern, url))
```

### Helper Functions
```python
import uuid
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

def generate_id(prefix: str = '') -> str:
    """Generate unique ID with optional prefix"""
    unique_id = str(uuid.uuid4())
    return f"{prefix}_{unique_id}" if prefix else unique_id

def generate_short_id(length: int = 8) -> str:
    """Generate short unique ID"""
    return str(uuid.uuid4()).replace('-', '')[:length]

def hash_string(text: str) -> str:
    """Generate SHA256 hash of string"""
    return hashlib.sha256(text.encode()).hexdigest()

def utc_now() -> datetime:
    """Get current UTC datetime"""
    return datetime.now(timezone.utc)

def serialize_datetime(dt: datetime) -> str:
    """Serialize datetime to ISO format"""
    return dt.isoformat() if dt else None

def deserialize_datetime(dt_str: str) -> Optional[datetime]:
    """Deserialize datetime from ISO format"""
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely parse JSON string"""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default

def safe_json_dumps(obj: Any, default: str = '{}') -> str:
    """Safely serialize object to JSON"""
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return default

def flatten_dict(d: Dict[str, Any], separator: str = '.') -> Dict[str, Any]:
    """Flatten nested dictionary"""
    def _flatten(obj, parent_key=''):
        items = []
        for k, v in obj.items():
            new_key = f"{parent_key}{separator}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(_flatten(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    return _flatten(d)
```

---

## 📝 **Logging Configuration**

### Structured Logging Setup
```python
import logging
import structlog
from typing import Any, Dict

def configure_logging(
    log_level: str = 'INFO',
    json_format: bool = False,
    include_timestamp: bool = True
) -> None:
    """Configure structured logging for the application"""
    
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(message)s'
    )
    
    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]
    
    if include_timestamp:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))
    
    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a configured logger instance"""
    return structlog.get_logger(name)

# Context manager for adding context to logs
class LogContext:
    def __init__(self, **context):
        self.context = context
    
    def __enter__(self):
        structlog.contextvars.bind_contextvars(**self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        structlog.contextvars.clear_contextvars()
```

---

## 🚨 **Exception Handling**

### Custom Exception Classes
```python
class VirtualPyTestException(Exception):
    """Base exception for VirtualPyTest"""
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)

class DeviceException(VirtualPyTestException):
    """Device-related exceptions"""
    pass

class DeviceNotFoundError(DeviceException):
    """Device not found"""
    def __init__(self, device_id: str):
        super().__init__(
            f"Device not found: {device_id}",
            error_code="DEVICE_NOT_FOUND",
            details={"device_id": device_id}
        )

class DeviceOfflineError(DeviceException):
    """Device is offline"""
    def __init__(self, device_id: str):
        super().__init__(
            f"Device is offline: {device_id}",
            error_code="DEVICE_OFFLINE",
            details={"device_id": device_id}
        )

class TestExecutionException(VirtualPyTestException):
    """Test execution related exceptions"""
    pass

class TestCaseNotFoundError(TestExecutionException):
    """Test case not found"""
    def __init__(self, test_case_id: str):
        super().__init__(
            f"Test case not found: {test_case_id}",
            error_code="TEST_CASE_NOT_FOUND",
            details={"test_case_id": test_case_id}
        )

class HostException(VirtualPyTestException):
    """Host-related exceptions"""
    pass

class HostNotAvailableError(HostException):
    """No available host for execution"""
    def __init__(self, requirements: List[str]):
        super().__init__(
            f"No available host with capabilities: {requirements}",
            error_code="HOST_NOT_AVAILABLE",
            details={"required_capabilities": requirements}
        )
```

---

## 🔗 **Integration Examples**

### Using Shared Configuration
```python
# In backend_server
from shared.lib.config.settings import shared_config

app.config['SECRET_KEY'] = shared_config.security.secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = shared_config.database.url

# In backend_host
from shared.lib.config.settings import shared_config

supabase_client = create_client(
    shared_config.external_services.supabase_url,
    shared_config.external_services.supabase_anon_key
)
```

### Using Data Models
```python
# In backend_host
from shared.lib.models.device import Device, DeviceType, DeviceStatus
from shared.lib.utils.helpers import generate_id, utc_now

def create_device(name: str, device_type: str, host_id: str) -> Device:
    return Device(
        id=generate_id('dev'),
        name=name,
        device_type=DeviceType(device_type),
        model='unknown',
        host_id=host_id,
        status=DeviceStatus.OFFLINE,
        capabilities=[],
        configuration={},
        last_seen=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now()
    )
```

### Using Logging
```python
# In any service
from shared.lib.utils.logging_config import configure_logging, get_logger, LogContext

# Configure logging at startup
configure_logging(log_level='INFO', json_format=True)

# Use in code
logger = get_logger(__name__)

def execute_test(test_case_id: str):
    with LogContext(test_case_id=test_case_id):
        logger.info("Starting test execution")
        
        try:
            # Execute test
            logger.info("Test completed successfully")
        except Exception as e:
            logger.error("Test failed", error=str(e))
            raise
```

---

## 🔧 **Development Guidelines**

### Adding New Utilities
1. **Place in appropriate module** (config, models, utils)
2. **Add type hints** for all functions and classes
3. **Include docstrings** with examples
4. **Add unit tests** for new functionality
5. **Update imports** in `__init__.py`

### Configuration Best Practices
- **Environment Variables**: Use for all configurable values
- **Default Values**: Provide sensible defaults
- **Validation**: Validate configuration at startup
- **Documentation**: Document all configuration options

### Model Design Principles
- **Immutability**: Use dataclasses for data models
- **Validation**: Validate data in model constructors
- **Serialization**: Provide `to_dict()` methods
- **Type Safety**: Use enums for constrained values

---

**Want to see how services use shared components? Check [Backend Core Documentation](backend-core.md)!** 🔧
