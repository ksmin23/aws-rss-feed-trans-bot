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
  aws_events_targets
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

    sg_rss_feed_trans_bot = aws_ec2.SecurityGroup(self, 'RssFeedTransBotSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for rss feed trans bot',
      security_group_name='rss-feed-trans-bot'
    )
    core.Tags.of(sg_rss_feed_trans_bot).add('Name', 'rss-feed-trans-bot')

    s3_lib_bucket_name = self.node.try_get_context('lib_bucket_name')

    #XXX: https://github.com/aws/aws-cdk/issues/1342
    s3_lib_bucket = s3.Bucket.from_bucket_name(self, id, s3_lib_bucket_name)

    bs4_lib_layer = _lambda.LayerVersion(self, 'Bs4Lib',
      layer_version_name='bs4-lib',
      compatible_runtimes=[_lambda.Runtime.PYTHON_3_7],
      code=_lambda.Code.from_bucket(s3_lib_bucket, 'var/bs4-lib.zip')
    )

    feedparser_lib_layer = _lambda.LayerVersion(self, 'FeedParserLib',
      layer_version_name='feedparser-lib',
      compatible_runtimes=[_lambda.Runtime.PYTHON_3_7],
      code=_lambda.Code.from_bucket(s3_lib_bucket, 'var/feedparser-lib.zip')
    )

    googletrans_lib_layer = _lambda.LayerVersion(self, 'GoogletransLib',
      layer_version_name='googletrans-lib',
      compatible_runtimes=[_lambda.Runtime.PYTHON_3_7],
      code=_lambda.Code.from_bucket(s3_lib_bucket, 'var/googletrans-lib.zip')
    )

    lambda_fn_env = {
      'REGION_NAME': core.Aws.REGION,
      'S3_BUCKET_NAME': s3_bucket.bucket_name,
      'S3_OBJ_KEY_PREFIX': 'whats-new',
      'PRESIGNED_URL_EXPIRES_IN': '{}'.format(86400*7),
      'EMAIL_FROM_ADDRESS': self.node.try_get_context('email_from_address'),
      'EMAIL_TO_ADDRESSES': self.node.try_get_context('email_to_addresses'),
      'TRANS_DEST_LANG': self.node.try_get_context('trans_dest_lang'),
      'DRY_RUN': self.node.try_get_context('dry_run')
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
      layers=[bs4_lib_layer, feedparser_lib_layer, googletrans_lib_layer],
      security_groups=[sg_rss_feed_trans_bot],
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

    # Run every hour
    # See https://docs.aws.amazon.com/lambda/latest/dg/tutorial-scheduled-events-schedule-expressions.html
    scheduled_event_rule = aws_events.Rule(self, 'RssFeedScheduledRule',
      schedule=aws_events.Schedule.cron(
        minute='0',
        hour='*',
        month='*',
        week_day='*',
        year='*'
      ),
    )
    scheduled_event_rule.add_target(aws_events_targets.LambdaFunction(rss_feed_trans_bot_lambda_fn))

    log_group = aws_logs.LogGroup(self, 'RssFeedTransBotLogGroup',
      log_group_name='/aws/lambda/RssFeedTransBot',
      retention=aws_logs.RetentionDays.THREE_DAYS)
    log_group.grant_write(rss_feed_trans_bot_lambda_fn)

