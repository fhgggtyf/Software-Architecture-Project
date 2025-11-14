# ADR-001: Docker Containerization

**Status:** Accepted  
**Date:** 2025-11-14  
**Decision Makers:** Development Team  
**Technical Story:** Deployment standardization and environment consistency

## Context and Problem Statement

The retail management system needs to be deployed consistently across different environments (development, testing, production). We need to ensure that:
- The application runs identically regardless of the host environment
- Dependencies are properly isolated
- Database and logs persist across container restarts
- The deployment process is simple and reproducible

## Decision Drivers

* **Consistency**: Eliminate "works on my machine" problems
* **Portability**: Deploy to any Docker-capable host
* **Isolation**: Separate application dependencies from host system
* **Reproducibility**: Standardize builds and deployments
* **Scalability**: Enable future orchestration with Kubernetes or Docker Swarm
* **Developer Experience**: Simplify local development and testing

## Considered Options

### Option 1: Native Python Installation
**Pros:**
- Direct access to system resources
- No containerization overhead
- Simpler for basic deployments

**Cons:**
- Dependency conflicts with host system
- Difficult to reproduce environments
- Manual setup on each host
- Version drift across environments

### Option 2: Virtual Machines
**Pros:**
- Strong isolation
- Full OS control

**Cons:**
- Heavy resource overhead
- Slower startup times
- Complex management
- Larger deployment artifacts

### Option 3: Docker Containerization  **SELECTED**
**Pros:**
- Lightweight compared to VMs
- Fast startup times
- Excellent portability
- Industry standard
- Large ecosystem of tools
- Easy to version control (Dockerfile)
- Simple volume management for persistence

**Cons:**
- Requires Docker runtime
- Learning curve for team
- Additional layer of complexity

## Decision Outcome

**Chosen option:** Docker Containerization (Option 3)

We will containerize the retail application using Docker because it provides the best balance of isolation, portability, and performance. The decision is implemented through:

1. **Dockerfile**: Defines the application image
2. **docker-compose.yml**: Orchestrates the service with proper volumes and configuration

### Implementation Details

#### Dockerfile Structure
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY src/ /app/
RUN pip install --break-system-packages [dependencies]
EXPOSE 8000
CMD ["python", "app_web.py"]
```

#### Docker Compose Configuration
```yaml
services:
  retailapp:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ../db:/app/db        # Database persistence
      - ../logs:/app/logs    # Log persistence
    environment:
      - RETAIL_DB_PATH=/app/db/retail.db
      - RETAIL_SCHEMA_PATH=/app/db/init.sql
    restart: unless-stopped
```

### Consequences

**Positive:**
- Consistent environment across all deployments
- Simple deployment process: `docker-compose up`
- Database and logs persist via volume mounts
- Easy to rollback by changing image tags
- Enables CI/CD pipeline integration
- Facilitates future scaling and orchestration

**Negative:**
- Requires Docker to be installed on host
- Slight performance overhead (minimal with modern Docker)
- Team needs Docker knowledge
- Volume permissions may need adjustment on some hosts

**Neutral:**
- Database runs in the same container (acceptable for SQLite; would be separated for production-grade systems)
- Network isolation limits direct access (can expose additional ports as needed)

## Validation

The containerization approach will be validated by:
1. **Build Success**: Dockerfile builds without errors
2. **Startup Test**: Container starts and serves requests on port 8000
3. **Persistence Test**: Data survives container restart
4. **Multi-Environment**: Same image runs on dev/test/prod

## Compliance

This decision aligns with:
- Modern DevOps practices
- Cloud-native application principles
- Industry standards for microservices
- Security best practices (isolated environments)

## Related Decisions

- **ADR-002**: Observability - Logs are persisted via volumes
- **ADR-003**: Resilience - Container restart policies handle failures
- Future: Kubernetes deployment will build on this foundation

## Notes

- Initial implementation uses a single container for simplicity
- Future enhancements may separate web tier, database tier, and monitoring
- Volume mounts ensure zero-downtime data persistence
- The `restart: unless-stopped` policy ensures high availability
