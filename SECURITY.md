# Security Policy

## Supported Versions

We take security seriously and provide security updates for the following versions of MyAstroBoard:

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < latest| :x:                |

We recommend always using the latest version to ensure you have the most recent security patches and updates.

## Security Model

MyAstroBoard is designed as a **self-hosted application** intended to run on:
- Personal home servers
- Private networks
- Behind reverse proxies with authentication

### Architecture Security Considerations

#### Authentication
- Built-in user authentication system with password hashing
- User credentials stored in `data/users.json` with bcrypt hashed passwords
- Session management via Flask sessions
- Default admin user requires password change on first login

#### Data Storage
- User configurations stored in `data/config.json`
- Equipment profiles stored in `data/equipments/`
- Cached astronomy data in `data/cache/`
- Application logs in `data/myastroboard.log`
- All data persisted in Docker volumes

## Reporting a Vulnerability

We appreciate your efforts to responsibly disclose security vulnerabilities.

### How to Report

**Do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities by:

1. **Opening a private security advisory** on GitHub:
   - Go to the repository's Security tab
   - Click "Report a vulnerability"
   - Fill out the advisory form with details

2. **Or contact the maintainers directly**:
   - Create a private issue and tag maintainers
   - Use encrypted communication if possible

### What to Include

When reporting a vulnerability, please include:

- **Type of vulnerability** (e.g., XSS, SQL injection, authentication bypass)
- **Full paths** of affected source files
- **Location** of the affected code (tag/branch/commit or direct URL)
- **Step-by-step instructions** to reproduce the issue
- **Proof-of-concept or exploit code** (if possible)
- **Impact assessment** - what could an attacker accomplish?
- **Suggested fix** (if you have one)
- **Your contact information** for follow-up

### What to Expect

- **Initial Response**: Within 48 hours acknowledging receipt
- **Assessment**: Within 5 business days with initial assessment
- **Updates**: Regular updates on progress (at least weekly)
- **Fix Timeline**: Depends on severity
  - **Critical**: Within 7 days
  - **High**: Within 14 days
  - **Medium**: Within 30 days
  - **Low**: Within 60 days
- **Disclosure**: Coordinated disclosure after fix is released

## Vulnerability Handling Process

1. **Report Received**: Security team acknowledges receipt
2. **Validation**: Team reproduces and validates the vulnerability
3. **Assessment**: Severity rating assigned (Critical/High/Medium/Low)
4. **Fix Development**: Security patch developed and tested
5. **Release**: New version released with fix
6. **Disclosure**: Public disclosure coordinated with reporter
7. **Credit**: Reporter credited in release notes (if desired)

## Security Best Practices for Users

### Deployment Security

#### Network Security
- **Run on private networks** only (home LAN, VPN)
- **Use reverse proxy** with HTTPS (see [REVERSE_PROXY.md](docs/6.REVERSE_PROXY.md))
- **Enable authentication** for all users
- **Use firewall rules** to restrict access
- **Avoid public exposure** without additional security layers

#### Authentication
- **Change default credentials** immediately
- **Use strong passwords** (16+ characters, mixed case, numbers, symbols)
- **Regularly update passwords**
- **Limit user accounts** to trusted individuals
- **Enable HTTPS** when accessing over network

#### Docker Security
- **Keep Docker updated** to latest stable version
- **Review Docker socket permissions** carefully
- **Use Docker networks** for container isolation
- **Regularly update base images**
- **Scan images** for vulnerabilities

#### File Permissions
- **Secure data directory** (`data/`) with appropriate permissions
- **Protect users.json** (contains hashed passwords)
- **Protect config.json** (contains location and settings)
- **Review log files** for suspicious activity

### Maintenance

#### Keep Updated
```bash
# Pull latest image
docker-compose pull

# Restart with latest version
docker-compose down
docker-compose up -d
```

#### Regular Monitoring
- **Review logs** in `data/myastroboard.log`
- **Monitor Docker containers** for unexpected activity
- **Check system metrics** for anomalies
- **Audit user accounts** periodically

#### Backup Strategy
- **Regular backups** of the `data/` directory
- **Secure backup storage** (encrypted if possible)
- **Test restoration** procedures
- **Keep multiple backup versions**

### Environment Variables

Sensitive configuration should use environment variables:

```yaml
# docker-compose.yml
environment:
  - SECRET_KEY=${SECRET_KEY}  # Flask secret key
  - LOG_LEVEL=INFO
  - CONSOLE_LOG_LEVEL=WARNING
```

Generate strong secret keys:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Known Security Considerations

### Intentional Design Choices

#### 1. Session Management
- **Risk**: Flask session-based authentication
- **Mitigation**: Use HTTPS, secure secret keys, short session timeouts
- **Enhancement**: Consider adding 2FA for sensitive deployments

### External Dependencies

MyAstroBoard relies on:
- **Python packages** (see `requirements.txt`)
- **External APIs** (Open-Meteo for weather)

Security considerations:
- **Dependency updates**: Regularly update dependencies
- **Vulnerability scanning**: Monitor for CVEs
- **Supply chain**: Verify image sources and signatures

## Security Features

### Current Protections

✅ **Password Hashing**: Bcrypt for password storage  
✅ **Input Validation**: Sanitization of user inputs  
✅ **Session Management**: Flask-Session with secure cookies  
✅ **Error Handling**: No sensitive info in error messages  
✅ **Logging**: Comprehensive activity logging  
✅ **File Isolation**: Containerized environment  

### Planned Enhancements

🔄 **Rate Limiting**: API rate limiting to prevent abuse  
🔄 **CSRF Protection**: Enhanced CSRF token management  
🔄 **Content Security Policy**: CSP headers for XSS protection  
🔄 **Security Headers**: Additional HTTP security headers  
🔄 **Audit Trail**: Enhanced security event logging  

## Scope

### In Scope

Security vulnerabilities in:
- Authentication and authorization mechanisms
- User data handling and storage
- API endpoints and input validation
- Session management
- Docker configuration security
- Dependency vulnerabilities
- Cross-site scripting (XSS)
- SQL injection (if applicable)
- Server-side request forgery (SSRF)
- Path traversal
- Command injection

### Out of Scope

The following are out of scope:
- **Denial of Service** (DoS) attacks - as a self-hosted app, rate limiting is user's responsibility
- **Physical security** of the host system
- **Social engineering** attacks
- **Vulnerabilities in third-party services** (Open-Meteo API, Docker Hub)
- **Brute force attacks** (mitigate with firewall/fail2ban)

## Security Resources

### References

- [OWASP Top Ten](https://owasp.org/www-project-top-ten/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Flask Security Considerations](https://flask.palletsprojects.com/en/latest/security/)
- [Python Security Guide](https://python.readthedocs.io/en/stable/library/security_warnings.html)

### Tools for Security Testing

Users can test their deployment with:
- **OWASP ZAP**: Web application security scanner
- **Docker Bench**: Docker security configuration checker
- **Trivy**: Container vulnerability scanner
- **Bandit**: Python security linter

Example security scan:
```bash
# Scan Docker image for vulnerabilities
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image myastroboard/myastroboard:latest

# Scan Python code for security issues
bandit -r backend/
```

## Hall of Fame

We recognize security researchers who responsibly disclose vulnerabilities:

<!-- Security researchers will be listed here -->

_No security vulnerabilities have been reported yet._

---

Thank you for helping keep MyAstroBoard and its users safe! 🔒🌙
