#!/usr/bin/env python3

import aws_cdk as cdk

from aws_rss_feed_trans_bot.aws_rss_feed_trans_bot_stack import AwsRssFeedTransBotStack


app = cdk.App()
AwsRssFeedTransBotStack(app, "AwsRssFeedTransBot")

app.synth()
