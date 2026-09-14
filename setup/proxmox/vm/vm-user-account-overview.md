# VirtualPyTest User Account Overview

## User Types Created

### Team Users (Human Access)
**Purpose**: SSH access for development and management
- **Accounts**: member1, member2, member3 (one per team member)
- **Access**: Full SSH login + sudo privileges
- **Use Case**: Deploy code, restart services, system administration
- **Security**: Can manage VMs but limited by sudo permissions

### Service Account (vpt_user)
**Purpose**: Run application services with minimal privileges
- **Account**: Single `vpt_user` account across all VMs
- **Access**: No SSH login, no password, systemd-only
- **Use Case**: Execute VirtualPyTest services (Flask API, React app, etc.)
- **Security**: Limited damage scope if compromised

## Why Two Types of Users?

### Security Separation Principle
**"Never run services as your own user account"**

- **Risk with Team Users**: If member1 account compromised, attacker gets full SSH access
- **Benefit with vpt_user**: If service compromised, attacker only affects that one service

### Real-World Example
```
❌ BAD: Flask API runs as member1
   Compromised API = Full server access

✅ GOOD: Flask API runs as vpt_user
   Compromised API = Only API access (limited damage)
```

## User Creation Process

### Automatic Setup
1. **Base Setup**: Debian prerequisites script creates `vpt_user`
2. **Service Installation**: Each VM install script configures services to run as `vpt_user`
3. **Team Access**: Manual creation of team user accounts (member1, member2, etc.)

### Account Properties
```
vpt_user:
├── No SSH login allowed
├── No password (systemd only)
├── Minimal file permissions
├── Single purpose: run services
└── Consistent across all VMs

Team Users (member1, member2, etc.):
├── SSH login allowed
├── Password authentication
├── sudo privileges for management
├── Multiple purposes: deploy, monitor, debug
└── One account per team member
```

## Service Running as vpt_user

### VirtualPyTest Services
- **Backend Server VM**: Flask API service
- **Frontend VM**: React web application
- **Host VMs**: Device control services
- **Infrastructure**: Monitoring, database services (use system accounts)

### Systemd Configuration
```ini
[Service]
User=vpt_user
Group=vpt_user
ExecStart=/path/to/app
# No login shell access
```

## Security Benefits

### Damage Containment
- **Service Compromise**: Limited to one application
- **Team Account Compromise**: Full server management access
- **Defense in Depth**: Multiple protection layers

### Audit & Compliance
- **Clear Separation**: Services vs human access
- **Accountability**: Track who does what
- **Least Privilege**: Services get minimum required access

## Management Implications

### For Team Members
- **SSH Access**: Use personal account (member1, member2)
- **Service Management**: `sudo systemctl restart service-name`
- **Code Deployment**: Access via personal SSH account

### For Security
- **Regular Audits**: Review user access and service accounts
- **Password Policies**: Strong passwords for team accounts
- **Access Reviews**: Remove inactive team member accounts

---

**Key Takeaway**: `vpt_user` ensures services run with limited privileges. Team users get management access. This separation protects your infrastructure if any single component is compromised.