# Retail Store Application - Operations Runbook

**Version:** 1.0  
**Last Updated:** 2024-10-24  
**Maintainers:** Kwabena Sekyi-Djan, Jiacheng Xia

## Table of Contents
1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Deployment Procedures](#deployment-procedures)
4. [Operational Procedures](#operational-procedures)
5. [Monitoring and Health Checks](#monitoring-and-health-checks)
6. [Troubleshooting Guide](#troubleshooting-guide)
7. [Backup and Recovery](#backup-and-recovery)
8. [Security Procedures](#security-procedures)
9. [Performance Optimization](#performance-optimization)
10. [Maintenance Procedures](#maintenance-procedures)
11. [Emergency Procedures](#emergency-procedures)
12. [Contact Information](#contact-information)

## Overview

The Retail Store Application is a two-tier web application built with Python that provides:
- Product catalog management
- User registration and authentication
- Shopping cart functionality
- Checkout and payment processing
- Admin interface for product management
- Partner feed ingestion

### Key Components
- **Web Server:** ThreadingHTTPServer (Python stdlib)
- **Database:** SQLite (file-based)
- **Session Management:** In-memory with cookies
- **Payment Processing:** Mock service with circuit breaker
- **Concurrency:** Multi-threaded request handling

## System Architecture

### Technology Stack
- **Language:** Python 3.10+
- **Web Framework:** Built-in http.server
- **Database:** SQLite 3
- **Session Storage:** In-memory
- **Payment Gateway:** Mock service

### Key Design Patterns
- **Circuit Breaker:** Payment service failure handling
- **Strategy Pattern:** Payment method processing
- **Adapter Pattern:** Partner feed ingestion
- **DAO Pattern:** Database abstraction
- **Optimistic Locking:** Concurrent stock updates

## Deployment Procedures

### Prerequisites
- Python 3.10+ installed
- Virtual environment capability
- SQLite 3 (included with Python)
- Git (for source code management)

### Initial Deployment

#### 1. Environment Setup
```bash
# Clone repository
git clone https://github.com/fhgggtyf/Software-Architecture-Project.git
cd Software-Architecture-Project

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Verify Python version
python --version  # Should be 3.10+
```

#### 2. Database Initialization
```bash
# Database will be auto-created on first run
# Manual initialization (optional):
sqlite3 db/retail.db < db/init.sql

# Verify database creation
ls -la db/retail.db
```

#### 3. Application Startup
```bash
# Default configuration (localhost:8000)
python ./src/app_web.py

# Custom host/port
HOST=0.0.0.0 PORT=8080 python ./src/app_web.py

# With custom database path
RETAIL_DB_PATH=/path/to/custom.db python ./src/app_web.py
```

#### 4. Verification
```bash
# Test application health
curl http://localhost:8000/products

# Check database connectivity
sqlite3 db/retail.db "SELECT COUNT(*) FROM Product;"
```

### Production Deployment

#### Environment Variables
```bash
# Required
export HOST=0.0.0.0
export PORT=8080
export RETAIL_DB_PATH=/var/lib/retail/retail.db

# Optional
export RETAIL_SCHEMA_PATH=/opt/retail/db/init.sql
```

#### System Service (systemd)
Create `/etc/systemd/system/retail-app.service`:
```ini
[Unit]
Description=Retail Store Application
After=network.target

[Service]
Type=simple
User=retail
Group=retail
WorkingDirectory=/opt/retail
Environment=HOST=0.0.0.0
Environment=PORT=8080
Environment=RETAIL_DB_PATH=/var/lib/retail/retail.db
ExecStart=/opt/retail/.venv/bin/python /opt/retail/src/app_web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Service Management
```bash
# Enable and start service
sudo systemctl enable retail-app
sudo systemctl start retail-app

# Check status
sudo systemctl status retail-app

# View logs
sudo journalctl -u retail-app -f
```

## Operational Procedures

### Daily Operations

#### 1. Health Check
```bash
# Check application status
curl -f http://localhost:8000/products || echo "Application down"

# Check database
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Check disk space
df -h /var/lib/retail/
```

#### 2. User Management
```bash
# Create admin user
sqlite3 db/retail.db "
INSERT INTO User (username, password_hash, is_admin) 
VALUES ('admin', '$(echo -n 'password' | sha256sum | cut -d' ' -f1)', 1);
"

# List users
sqlite3 db/retail.db "SELECT username, is_admin FROM User;"
```

#### 3. Product Management
```bash
# Add product
sqlite3 db/retail.db "
INSERT INTO Product (name, price, stock) 
VALUES ('New Product', 29.99, 100);
"

# Update stock
sqlite3 db/retail.db "
UPDATE Product SET stock = 150 WHERE name = 'New Product';
"

# List products
sqlite3 db/retail.db "SELECT id, name, price, stock FROM Product;"
```

### Weekly Operations

#### 1. Database Maintenance
```bash
# Optimize database
sqlite3 db/retail.db "VACUUM;"

# Analyze performance
sqlite3 db/retail.db "ANALYZE;"

# Check database size
du -h db/retail.db
```

#### 2. Log Rotation
```bash
# Rotate application logs (if using external logging)
sudo logrotate -f /etc/logrotate.d/retail-app
```

#### 3. Performance Review
```bash
# Check active sessions (if monitoring implemented)
# Review error rates
# Analyze response times
```

## Monitoring and Health Checks

### Health Check Endpoints

#### Basic Health Check
```bash
# Application availability
curl -f http://localhost:8000/products

# Expected response: HTML product listing
```

#### Database Health
```bash
# Database connectivity
sqlite3 db/retail.db "SELECT 1;"

# Database integrity
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Table existence
sqlite3 db/retail.db "
SELECT name FROM sqlite_master 
WHERE type='table' AND name IN ('User', 'Product', 'Sale', 'SaleItem', 'Payment');
"
```

#### Payment Service Health
```bash
# Check circuit breaker status (if implemented)
# Monitor payment success rates
# Review error logs
```

### Monitoring Metrics

#### Key Performance Indicators
- **Response Time:** < 200ms for product listing
- **Availability:** > 99.5% uptime
- **Database Size:** Monitor growth rate
- **Active Sessions:** Track concurrent users
- **Payment Success Rate:** > 95%

#### Alerting Thresholds
- **Response Time:** > 1 second
- **Error Rate:** > 5%
- **Disk Space:** < 1GB free
- **Database Size:** > 10GB
- **Memory Usage:** > 80%

## Troubleshooting Guide

### Common Issues

#### 1. Application Won't Start

**Symptoms:**
- "Address already in use" error
- "Permission denied" error
- "Module not found" error

**Diagnosis:**
```bash
# Check port availability
netstat -tlnp | grep :8000

# Check permissions
ls -la src/app_web.py

# Check Python path
which python
python -c "import sys; print(sys.path)"
```

**Solutions:**
```bash
# Kill process using port
sudo lsof -ti:8000 | xargs kill -9

# Fix permissions
chmod +x src/app_web.py

# Activate virtual environment
source .venv/bin/activate
```

#### 2. Database Issues

**Symptoms:**
- "Database is locked" error
- "No such table" error
- "Integrity constraint" error

**Diagnosis:**
```bash
# Check database file
ls -la db/retail.db

# Check database integrity
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Check schema
sqlite3 db/retail.db ".schema"
```

**Solutions:**
```bash
# Recreate database
rm db/retail.db
sqlite3 db/retail.db < db/init.sql

# Fix permissions
chmod 664 db/retail.db
chown retail:retail db/retail.db
```

#### 3. Session Issues

**Symptoms:**
- Users logged out unexpectedly
- Cart contents lost
- "Session expired" errors

**Diagnosis:**
```bash
# Check application logs
# Monitor memory usage
# Check for server restarts
```

**Solutions:**
```bash
# Restart application
sudo systemctl restart retail-app

# Clear browser cookies
# Check server memory
free -h
```

#### 4. Payment Processing Issues

**Symptoms:**
- "Payment service unavailable" error
- Circuit breaker open
- Payment timeouts

**Diagnosis:**
```bash
# Check circuit breaker status
# Review payment logs
# Test payment service
```

**Solutions:**
```bash
# Reset circuit breaker (if implemented)
# Check payment service configuration
# Review network connectivity
```

### Error Codes and Messages

#### HTTP Status Codes
- **200:** Success
- **302:** Redirect (login required)
- **403:** Forbidden (insufficient permissions)
- **404:** Not found
- **500:** Internal server error

#### Application Errors
- **"Payment service temporarily unavailable"** - Circuit breaker open
- **"Insufficient stock"** - Product out of stock
- **"You must be logged in"** - Session expired
- **"Payment failed"** - Payment processing error

## Backup and Recovery

### Backup Procedures

#### 1. Database Backup
```bash
# Full database backup
cp db/retail.db db/backups/retail_$(date +%Y%m%d_%H%M%S).db

# Compressed backup
sqlite3 db/retail.db ".backup db/backups/retail_$(date +%Y%m%d_%H%M%S).db"
gzip db/backups/retail_$(date +%Y%m%d_%H%M%S).db

# Automated backup script
#!/bin/bash
BACKUP_DIR="/opt/retail/backups"
mkdir -p $BACKUP_DIR
sqlite3 /var/lib/retail/retail.db ".backup $BACKUP_DIR/retail_$(date +%Y%m%d_%H%M%S).db"
find $BACKUP_DIR -name "retail_*.db" -mtime +30 -delete
```

#### 2. Application Backup
```bash
# Backup application code
tar -czf retail_app_$(date +%Y%m%d_%H%M%S).tar.gz \
    --exclude='.venv' \
    --exclude='db/retail.db' \
    --exclude='__pycache__' \
    /opt/retail/
```

### Recovery Procedures

#### 1. Database Recovery
```bash
# Restore from backup
cp db/backups/retail_20241024_120000.db db/retail.db

# Verify integrity
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Restart application
sudo systemctl restart retail-app
```

#### 2. Full System Recovery
```bash
# Stop application
sudo systemctl stop retail-app

# Restore database
cp /backup/location/retail.db /var/lib/retail/retail.db

# Restore application
tar -xzf retail_app_backup.tar.gz -C /opt/

# Restart application
sudo systemctl start retail-app
```

## Security Procedures

### Access Control

#### 1. User Management
```bash
# Create admin user
sqlite3 db/retail.db "
INSERT INTO User (username, password_hash, is_admin) 
VALUES ('admin', '$(echo -n 'secure_password' | sha256sum | cut -d' ' -f1)', 1);
"

# Remove user
sqlite3 db/retail.db "DELETE FROM User WHERE username = 'old_user';"
```

#### 2. Database Security
```bash
# Set proper permissions
chmod 600 db/retail.db
chown retail:retail db/retail.db

# Enable WAL mode for better concurrency
sqlite3 db/retail.db "PRAGMA journal_mode=WAL;"
```

### Security Monitoring

#### 1. Failed Login Attempts
```bash
# Monitor failed authentications
# Review application logs for suspicious activity
# Check for brute force attempts
```

#### 2. Data Integrity
```bash
# Regular integrity checks
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Check for unauthorized modifications
# Monitor database file permissions
```

## Performance Optimization

### Database Optimization

#### 1. Index Creation
```sql
-- Add indexes for better performance
CREATE INDEX IF NOT EXISTS idx_product_name ON Product(name);
CREATE INDEX IF NOT EXISTS idx_sale_user_id ON Sale(user_id);
CREATE INDEX IF NOT EXISTS idx_sale_timestamp ON Sale(timestamp);
```

#### 2. Query Optimization
```bash
# Analyze query performance
sqlite3 db/retail.db "EXPLAIN QUERY PLAN SELECT * FROM Product WHERE name = 'Widget';"

# Update statistics
sqlite3 db/retail.db "ANALYZE;"
```

### Application Optimization

#### 1. Connection Pooling
- Already implemented with thread-local storage
- Monitor connection usage
- Adjust pool size if needed

#### 2. Session Management
- Monitor session count
- Implement session expiration
- Clean up expired sessions

## Maintenance Procedures

### Regular Maintenance

#### Daily
- Monitor application health
- Check error logs
- Verify database integrity
- Monitor disk space

#### Weekly
- Database optimization (VACUUM)
- Log rotation
- Performance review
- Security audit

#### Monthly
- Full system backup
- Security updates
- Performance analysis
- Capacity planning

### Database Maintenance

#### 1. Schema Updates
```bash
# Apply schema changes
sqlite3 db/retail.db < db/migrations/001_add_flash_sale.sql

# Verify schema version
sqlite3 db/retail.db "PRAGMA user_version;"
```

#### 2. Data Cleanup
```sql
-- Clean up old sessions (if implemented)
DELETE FROM Sessions WHERE created_at < datetime('now', '-30 days');

-- Archive old sales (if needed)
-- Move old data to archive tables
```

## Emergency Procedures

### Service Outage

#### 1. Immediate Response
```bash
# Check service status
sudo systemctl status retail-app

# Check logs
sudo journalctl -u retail-app --since "10 minutes ago"

# Restart service
sudo systemctl restart retail-app
```

#### 2. Database Corruption
```bash
# Stop application
sudo systemctl stop retail-app

# Check database integrity
sqlite3 db/retail.db "PRAGMA integrity_check;"

# Restore from backup
cp db/backups/retail_latest.db db/retail.db

# Restart application
sudo systemctl start retail-app
```

#### 3. High Load Situations
```bash
# Monitor system resources
top
htop

# Check database locks
sqlite3 db/retail.db "PRAGMA database_list;"

# Restart application if needed
sudo systemctl restart retail-app
```

### Data Recovery

#### 1. Point-in-Time Recovery
```bash
# Restore from specific backup
cp db/backups/retail_20241024_120000.db db/retail.db

# Verify data integrity
sqlite3 db/retail.db "SELECT COUNT(*) FROM Sale;"
```

#### 2. Partial Data Recovery
```sql
-- Recover specific records
INSERT INTO Product (name, price, stock) 
SELECT name, price, stock FROM backup_db.Product 
WHERE id NOT IN (SELECT id FROM Product);
```

## Contact Information

### Team Contacts
- **Primary Maintainer:** Kwabena Sekyi-Djan
- **Secondary Maintainer:** Jiacheng Xia
- **Emergency Contact:** [Your emergency contact]

### External Dependencies
- **Python Support:** Python.org documentation
- **SQLite Support:** SQLite.org documentation
- **System Support:** [Your system administrator]

### Escalation Procedures
1. **Level 1:** Check logs and restart service
2. **Level 2:** Contact primary maintainer
3. **Level 3:** Contact secondary maintainer
4. **Level 4:** Emergency procedures and external support

---

**Document Version:** 1.0  
**Last Updated:** 2024-10-24  
**Next Review:** 2024-11-24
