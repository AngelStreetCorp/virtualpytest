# VirtualPyTest Backend Server

## 🎯 **Overview**

Backend Server is the central API layer and orchestration engine that coordinates all VirtualPyTest system components. It serves as the communication hub between the frontend user interface and backend_host hardware controllers, managing business logic, test orchestration, and system-wide coordination.

## 🔧 **Software Stack**

- **Language**: Python 3.8+
- **Framework**: Flask web application with Gunicorn WSGI server
- **Process Management**: Supervisor for service orchestration
- **Real-time Communication**: Socket.IO for WebSocket connections
- **Deployment**: Docker containerization

## 🏗️ **Core Libraries & Frameworks**

- **Flask**: Web framework for REST API endpoints
- **Gunicorn**: WSGI server for production deployment
- **Socket.IO**: Real-time bidirectional communication
- **Pydantic**: Data validation and serialization
- **StructLog**: Structured logging and monitoring
- **Requests**: HTTP client for external service communication

## 📋 **Application Services**

### **API Services**
- **System Management**: Health monitoring, system status, and configuration
- **Test Management**: CRUD operations for test cases and test execution
- **Campaign Management**: Test campaign creation, scheduling, and orchestration
- **Host Coordination**: Hardware host registration, communication, and load balancing

### **Communication Services**
- **REST API Layer**: HTTP endpoints for client-server communication
- **WebSocket Service**: Real-time updates and live data streaming
- **Host Proxy Service**: Request routing to appropriate hardware hosts
- **Media Streaming**: Video/audio stream proxying and media management

### **Business Logic Services**
- **Test Orchestrator**: Automated test execution across multiple devices
- **Campaign Manager**: Test campaign lifecycle management
- **Host Registry**: Dynamic hardware host discovery and management
- **Database Layer**: Supabase PostgreSQL for data persistence

## 🎯 **Main Purpose**

Backend Server acts as the intelligent coordination layer that transforms VirtualPyTest from a collection of individual components into a cohesive testing platform. It provides the business logic, data management, and orchestration capabilities needed to execute complex automated testing workflows across distributed hardware environments while maintaining real-time visibility and control.

## 📚 **Technical Documentation**

- **[Services Configuration](config/services/README.md)** - Detailed service setup and configuration
- **[Docker Deployment](docker/README.md)** - Container deployment and orchestration
- **[Dockerfile](Dockerfile)** - Container build configuration
- **[Requirements](requirements.txt)** - Python dependencies and versions 