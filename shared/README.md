# VirtualPyTest Shared Library

Common utilities, models, and configuration shared across all VirtualPyTest services.

## 📦 **What's Included**

- **Configuration**: Environment settings, database config, security settings
- **Database**: Database access classes for all entities (devices, campaigns, users, navigation trees, etc.)
- **Executors**: Execution logic for campaigns, scripts, test steps, and automated workflows
- **Models**: Data models (Device, Host, NavigationTree, etc.)
- **Schemas**: Data validation schemas and parameter types
- **Utilities**: Helper functions including AI, image processing, **selector scoring** (UI automation), navigation, and more
- **Device Configs**: Hardware and device configuration files

## 🔧 **Installation**

```bash
# Install as editable package
pip install -e .

# Or install from requirements
pip install -r requirements.txt
```

## 📁 **Structure**

```
shared/src/lib/
├── config/                  # Configuration management
│   ├── settings.py          # Shared configuration classes
│   ├── constants.py         # System constants
│   ├── device_capabilities.py # Device capabilities
│   └── devices/             # Device configuration files
├── database/                # Database access classes
│   ├── device_models_db.py  # Device database operations
│   ├── users_db.py          # User management
│   ├── campaign_db.py       # Campaign operations
│   └── ... (25+ database modules)
├── executors/               # Execution logic
│   ├── campaign_executor.py # Campaign execution
│   ├── script_executor.py   # Script execution
│   └── step_executor.py     # Step execution
├── models/                  # Data models
│   ├── device.py            # Device data models
│   ├── host.py              # Host models
│   └── navigation_tree.py   # Navigation tree models
├── schemas/                 # Data validation
│   └── param_types.py       # Parameter type definitions
├── utils/                   # Utility functions
│   ├── selector_scoring.py  # UI selector scoring logic
│   ├── ai_utils.py          # AI/ML utilities
│   ├── image_utils.py       # Image processing
│   ├── navigation_utils.py  # Navigation helpers
│   └── ... (35+ utility modules)
└── __init__.py
```

## 🔧 **Environment Variables**

Copy the environment template and configure your credentials:

```bash
# Copy template
cp env.example .env

# Edit with your values
nano .env
```

Required environment variables (see `env.example`):
- `CLOUDFLARE_R2_ENDPOINT` - Cloudflare R2 endpoint URL
- `CLOUDFLARE_R2_ACCESS_KEY_ID` - Access key ID
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY` - Secret access key  
- `CLOUDFLARE_R2_PUBLIC_URL` - Public URL for file access
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_ANON_KEY` - Supabase anonymous key

## 🚀 **Usage**

### Configuration
```python
from shared.src.lib.config.settings import shared_config

# Access configuration
db_config = shared_config.database
security_config = shared_config.security
```

### Data Models
```python
from shared.src.lib.models.device import Device
from shared.src.lib.models.device_types import DeviceType

# Create device instance
device = Device(
    id="device1",
    name="Test Device",
    type=DeviceType.ANDROID_MOBILE
)
```

### Utilities
```python
from shared.src.lib.utils.selector_scoring import find_best_selector
from shared.src.lib.utils.ai_utils import generate_prompt

# Use selector scoring for UI automation
best_selector = find_best_selector(elements, platform='mobile')

# Use AI utilities
prompt = generate_prompt("analyze this screen")
```

## 🔧 **Configuration Management**

### Environment Variables
The shared library reads from these environment variables:

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/db
DB_HOST=localhost
DB_PORT=5432
DB_NAME=virtualpytest

# Security
SECRET_KEY=your-secret-key
JWT_SECRET=your-jwt-secret

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### Device Configuration
Device configurations are stored in `src/lib/config/devices/`:

```python
# Load device configuration
from shared.src.lib.config.devices import load_device_config

appium_config = load_device_config('appium_remote.json')
```

## 🧪 **Testing**

```bash
# Run tests (if available)
python -m pytest tests/

# Type checking
mypy shared/src/lib/
```

## 📝 **Adding New Shared Components**

1. **Models**: Add to `src/lib/models/`
2. **Configuration**: Add to `src/lib/config/`
3. **Database**: Add to `src/lib/database/`
4. **Executors**: Add to `src/lib/executors/`
5. **Schemas**: Add to `src/lib/schemas/`
6. **Utilities**: Add to `src/lib/utils/`
7. **Update `__init__.py`**: Export new components

## 🔄 **Versioning**

The shared library follows semantic versioning. When making changes:

1. **Patch** (1.0.1): Bug fixes, documentation
2. **Minor** (1.1.0): New features, backward compatible
3. **Major** (2.0.0): Breaking changes

## 🤝 **Contributing**

1. Add new components following existing patterns
2. Update documentation
3. Ensure backward compatibility
4. Test across all services that use shared lib

## 📋 **Dependencies**

Minimal dependencies to keep shared library lightweight:

- `typing-extensions`: Type hints
- `pydantic`: Data validation
- `python-dotenv`: Environment variables
- `requests`: HTTP client
- `structlog`: Logging
- `orjson`: Fast JSON handling 