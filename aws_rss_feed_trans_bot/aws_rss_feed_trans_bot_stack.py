#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

from aws_cdk import (
  core,
  aws_ec2,
  aws_iam,
  aws_s3 as s3,
  aws_lambda as _lambda,
  aws_logs,
  aws_events,
  aws_events_targets,
  aws_elasticache
)


class AwsRssFeedTransBotStack(core.Stack):

  def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
    super().__init__(scope, id, **kwargs)

    # The code that defines your stack goes here
    vpc = aws_ec2.Vpc(self, 'RssFeedTransBotVPC',
      max_azs=2,
      gateway_endpoints={
        'S3': aws_ec2.GatewayVpcEndpointOptions(
          service=aws_ec2.GatewayVpcEndpointAwsService.S3
        )
      }
    )

    s3_bucket = s3.Bucket(self, 'TransRecentAnncmtBucket',
      bucket_name='aws-rss-feed-{region}-{account}'.format(region=core.Aws.REGION,
        account=core.Aws.ACCOUNT_ID))

    s3_bucket.add_lifecycle_rule(prefix='whats-new-html/', id='whats-new-html',
      abort_incomplete_multipart_upload_after=core.Duration.days(3),
      expiration=core.Duration.days(7))

    sg_use_elasticache = aws_ec2.SecurityGroup(self, 'RssFeedTransBotCacheClientSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for redis client used rss feed trans bot',
      security_group_name='use-rss-feed-trans-bot-redis'
    )
    core.Tags.of(sg_use_elasticache).add('Name', 'use-rss-feed-trans-bot-redis')

    sg_elasticache = aws_ec2.SecurityGroup(self, 'RssFeedTransBotCacheSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for redis used rss feed trans bot',
      security_group_name='rss-feed-trans-bot-redis'
    )
    core.Tags.of(sg_elasticache).add('Name', 'rss-feed-trans-bot-redis')

    sg_elasticache.add_ingress_rule(peer=sg_use_elasticache, connection=aws_ec2.Port.tcp(6379), description='use-rss-feed-trans-bot-redis')

    elasticache_subnet_group = aws_elasticache.CfnSubnetGroup(self, 'RssFeedTransBotCacheSubnetGroup',
      description='subnet group for rss-feed-trans-bot-redis',
      subnet_ids=vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PRIVATE).subnet_ids,
      cache_subnet_group_name='rss-feed-trans-bot-redis'
    )

    translated_feed_cache = aws_elasticache.CfnCacheCluster(self, 'RssFeedTransBotCache',
      cache_node_type='cache.t3.small',
      num_cache_nodes=1,
      engine='redis',
      engine_version='5.0.5',
      auto_minor_version_upgrade=False,
      cluster_name='rss-feed-trans-bot-redis',
      snapshot_retention_limit=3,
      snapshot_window='17:00-19:00',
      preferred_maintenance_window='mon:19:00-mon:20:30',
      #XXX: Do not use referece for 'cache_subnet_group_name' - https://github.com/aws/aws-cdk/issues/3098
      cache_subnet_group_name=elasticache_subnet_group.cache_subnet_group_name, # Redis cluster goes to wrong VPC
      #cache_subnet_group_name='rss-feed-trans-bot-redis',
      vpc_security_group_ids=[sg_elasticache.security_group_id]
    )

    #XXX: If you're going to launch your cluster in an Amazon VPC, you need to create a subnet group before you start creating a cluster.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-elasticache-cache-cluster.html#cfn-elasticache-cachecluster-cachesubnetgroupname
    translated_feed_cache.add_depends_on(elasticache_subnet_group)

    sg_rss_feed_trans_bot = aws_ec2.SecurityGroup(self, 'RssFeedTransBotSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for rss feed trans bot',
      security_group_name='rss-feed-trans-bot'
    )
    core.Tags.of(sg_rss_feed_trans_bot).add('Name', 'rss-feed-trans-bot')

    s3_lib_bucket_name = self.node.try_get_context('lib_bucket_name')

    #XXX: https://github.com/aws/aws-cdk/issues/1342
    s3_lib_bucket = s3.Bucket.from_bucket_name(self, "S3LibBucketName", s3_lib_bucket_name)

    lambda_lib_layer = _lambda.LayerVersion(self, "RssFeedTransBotLib",
      layer_version_name="rss_feed_trans_bot-lib",
      compatible_runtimes=[_lambda.Runtime.PYTHON_3_7],
      code=_lambda.Code.from_bucket(s3_lib_bucket, "var/rss_feed_trans_bot-lib.zip")
    )

    lambda_fn_env = {
      'REGION_NAME': core.Aws.REGION,
      'S3_BUCKET_NAME': s3_bucket.bucket_name,
      'S3_OBJ_KEY_PREFIX': 'whats-new',
      'PRESIGNED_URL_EXPIRES_IN': '{}'.format(86400*7),
      'EMAIL_FROM_ADDRESS': self.node.try_get_context('email_from_address'),
      'EMAIL_TO_ADDRESSES': self.node.try_get_context('email_to_addresses'),
      'TRANS_DEST_LANG': self.node.try_get_context('trans_dest_lang'),
      'DRY_RUN': self.node.try_get_context('dry_run'),
      'ELASTICACHE_HOST': translated_feed_cache.attr_redis_endpoint_address
    }

    #XXX: Deploy lambda in VPC - https://github.com/aws/aws-cdk/issues/1342
    rss_feed_trans_bot_lambda_fn = _lambda.Function(self, 'RssFeedTransBot',
      runtime=_lambda.Runtime.PYTHON_3_7,
      function_name='RssFeedTransBot',
      handler='rss_feed_trans_bot.lambda_handler',
      description='Translate rss feed',
      code=_lambda.Code.asset('./src/main/python/RssFeedTransBot'),
      environment=lambda_fn_env,
      timeout=core.Duration.minutes(15),
      layers=[lambda_lib_layer],
      security_groups=[sg_rss_feed_trans_bot, sg_use_elasticache],
      vpc=vpc
    )

    rss_feed_trans_bot_lambda_fn.add_to_role_policy(aws_iam.PolicyStatement(**{
      "effect": aws_iam.Effect.ALLOW,
      "resources": [s3_bucket.bucket_arn, "{}/*".format(s3_bucket.bucket_arn)],
      "actions": ["s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject"]
    }))

    rss_feed_trans_bot_lambda_fn.add_to_role_policy(aws_iam.PolicyStatement(**{
      "effect": aws_iam.Effect.ALLOW,
      "resources": ["*"],
      "actions": ["ses:SendEmail"]
    }))

    # See https://docs.aws.amazon.com/lambda/latest/dg/tutorial-scheduled-events-schedule-expressions.html
    event_schedule = dict(zip(['minute', 'hour', 'month', 'week_day', 'year'],
      self.node.try_get_context('event_schedule').split(' ')))

    scheduled_event_rule = aws_events.Rule(self, 'RssFeedScheduledRule',
      schedule=aws_events.Schedule.cron(**event_schedule))

    scheduled_event_rule.add_target(aws_events_targets.LambdaFunction(rss_feed_trans_bot_lambda_fn))

    log_group = aws_logs.LogGroup(self, 'RssFeedTransBotLogGroup',
      log_group_name='/aws/lambda/RssFeedTransBot',
      retention=aws_logs.RetentionDays.THREE_DAYS)
    log_group.grant_write(rss_feed_trans_bot_lambda_fn)

