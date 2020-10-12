#!/usr/bin/env python3

from aws_cdk import core

from aws_rss_feed_trans_bot.aws_rss_feed_trans_bot_stack import AwsRssFeedTransBotStack


app = core.App()
AwsRssFeedTransBotStack(app, "aws-rss-feed-trans-bot")

app.synth()
