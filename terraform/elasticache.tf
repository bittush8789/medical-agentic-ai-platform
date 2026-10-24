# ==============================================================================
# AWS ElastiCache for Redis (Multi-AZ Cluster for 5ms Response Caching)
# Sharded Cluster Mode with In-Transit & At-Rest Encryption
# ==============================================================================

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.environment}-redis-subnet-group"
  subnet_ids = aws_subnet.database[*].id
}

resource "aws_security_group" "redis" {
  name        = "${var.environment}-redis-cluster-sg"
  description = "Permit incoming Redis traffic from EKS worker nodes"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis access from EKS nodes"
    from_port       = 6379
    to_port         = 6379
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
    Name = "${var.environment}-redis-cluster-sg"
  }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.environment}-medguide-cache"
  description                = "MedGuide AI high-speed query cache and rate limiter"
  node_type                  = var.redis_node_type
  port                       = 6379
  parameter_group_name       = "default.redis7.cluster.on"
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]

  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  num_node_groups         = var.redis_num_shards
  replicas_per_node_group = 1

  maintenance_window       = "sun:05:00-sun:06:00"
  snapshot_retention_limit = 7
  snapshot_window          = "02:00-03:00"

  tags = {
    Name = "${var.environment}-medguide-redis-cluster"
  }
}
