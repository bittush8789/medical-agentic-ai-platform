# ==============================================================================
# AWS RDS PostgreSQL (Multi-AZ Enterprise Database for 1M Scale)
# Replaces SQLite with Aurora/Postgres Multi-AZ HA & Storage Autoscaling
# ==============================================================================

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# ── Store Database Credentials in AWS Secrets Manager ──

resource "aws_secretsmanager_secret" "db_secret" {
  name        = "${var.environment}-medguide-db-credentials"
  description = "Master credentials for MedGuide AI PostgreSQL database"
}

resource "aws_secretsmanager_secret_version" "db_secret_val" {
  secret_id = aws_secretsmanager_secret.db_secret.id
  secret_string = jsonencode({
    engine   = "postgres"
    host     = aws_db_instance.postgres.address
    port     = aws_db_instance.postgres.port
    username = var.db_username
    password = random_password.db_password.result
    database = var.db_name
  })
}

# ── DB Subnet Group ──

resource "aws_db_subnet_group" "rds" {
  name        = "${var.environment}-rds-subnet-group"
  subnet_ids  = aws_subnet.database[*].id
  description = "Isolated database subnets for MedGuide RDS PostgreSQL"
}

# ── Database Security Group ──

resource "aws_security_group" "rds" {
  name        = "${var.environment}-rds-postgres-sg"
  description = "Permit incoming PostgreSQL traffic strictly from EKS worker nodes"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL access from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.environment}-rds-postgres-sg"
  }
}

# ── PostgreSQL Parameter Group (Tuned for 1M concurrency) ──

resource "aws_db_parameter_group" "postgres" {
  name   = "${var.environment}-postgres16-params"
  family = "postgres16"

  parameter {
    name  = "max_connections"
    value = "5000"
  }

  parameter {
    name  = "idle_in_transaction_session_timeout"
    value = "60000" # 60 seconds
  }

  parameter {
    name  = "statement_timeout"
    value = "30000" # 30 seconds
  }
}

# ── RDS PostgreSQL Multi-AZ Instance ──

resource "aws_db_instance" "postgres" {
  identifier             = "${var.environment}-medguide-db"
  engine                 = "postgres"
  engine_version         = "16.2"
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  max_allocated_storage  = var.db_max_allocated_storage
  storage_type           = "gp3"
  storage_encrypted      = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_password.result

  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name

  multi_az               = true
  publicly_accessible    = false
  skip_final_snapshot    = false
  final_snapshot_identifier = "${var.environment}-medguide-final-snapshot"
  deletion_protection    = true

  backup_retention_period   = 14
  backup_window             = "03:00-04:00"
  maintenance_window        = "Mon:04:00-Mon:05:00"
  auto_minor_version_upgrade = true

  tags = {
    Name = "${var.environment}-medguide-rds-postgres"
  }
}
