# AWS Recent Announcements Rss Feed Translation Bot

영문 [AWS의 최신 소식 (What's New with AWS?)](https://aws.amazon.com/new/)을 한국어로 기계 번역해서 영문과 한국어 번역 내용(아래 그림 참조)을 email로 전송해주는 프로젝트.<br/>

  **Figure 1.** 영문 AWS의 최신 소식을 한국어로 번역한 결과
  ![rss_feed_trans_bot_results](./assets/rss_feed_trans_bot_results.png)

## Architecture
  ![rss-feed-trans-bot-arch](./assets/rss-feed-trans-bot-arch.svg)

## Deployment

1. [Getting Started With the AWS CDK](https://docs.aws.amazon.com/cdk/latest/guide/getting_started.html)를 참고해서 cdk를 설치하고,
cdk를 실행할 때 사용할 IAM User를 생성한 후, `~/.aws/config`에 등록한다.
예를 들어서, `cdk_user`라는 IAM User를 생성 한 후, 아래와 같이 `~/.aws/config`에 추가로 등록한다.

    ```shell script
    $ cat ~/.aws/config
    [profile cdk_user]
    aws_access_key_id=AKIAIOSFODNN7EXAMPLE
    aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    region=us-east-1
    ```

2. Lambda Layer에 등록할 Python 패키지를 저장할 s3 bucket을 생성한다. 예를 들어, `lambda-layer-resources` 라는 이름의 s3 bucket을 생성한다.

   ```shell script
    $ aws s3api create-bucket --bucket lambda-layer-resources --region us-east-1
    ```

3. 아래와 같이 소스 코드를 git clone 한 후에, `build-aws-lambda-layer.sh` 를 이용해서
Lambda Layer에 등록할 Python 패키지를 생성해서 s3에 저장한다.

    ```shell script
    $ git clone https://github.com/ksmin23/aws-rss-feed-trans-bot.git
    $ cd aws-rss-feed-trans-bot
    $ python3 -m venv .env
    $ source .env/bin/activate
    (.env) $ pip install -r requirements.txt
    (.env) $ ./build-aws-lambda-layer.sh lambda-layer-resources/var
    ```

4. `cdk.context.json` 파일을 열어서, `lib_bucket_name`에 Lambda Layer에 등록할 Python 패키지가 저장된 s3 bucket 이름을 적고,<br/>`email_from_address`과 `email_to_addresses`에 e-mail 발신자와 수신자들 목록을 각각 넣는다.<br/> RSS Feed를 읽는 주기를 변경하고자 하는 경우, `event_schedule`을 crontab 문법 처럼 등록 한다.<br/>
`event_schedule` 기본 값은 매 시간 마다 RSS Feed를 읽어서 번역한다.

    ```json
    {
      "lib_bucket_name": "Your-S3-Bucket-Name-Of-Lambda-Layer-Lib",
      "email_from_address": "Your-Sender-Email-Addr",
      "email_to_addresses": "Your-Receiver-Email-Addr-List",
      "dry_run": "false",
      "trans_dest_lang": "ko",
      "event_schedule": "0 * * * *"
    }
    ```
   `email_from_address`은 [Amazon SES에서 이메일 주소 확인](https://docs.aws.amazon.com/ses/latest/DeveloperGuide/verify-email-addresses.html)를 참고해서 반드시 사용 가능한 email 주소인지 확인한다. (배포 전에 한번만 확인 하면 된다.)
    예를 들어, `sender@amazon.com`라는 email 주소를 확인하려면 다음과 같이 한다.
      ```
      aws ses verify-email-identity --email-address sender@amazon.com
      ```

5. `cdk deploy` 명령어를 이용해서 배포한다.
    ```shell script
    (.env) $ cdk --profile=cdk_user deploy
    ```

6. 배포한 애플리케이션을 삭제하려면, `cdk destroy` 명령어를 아래와 같이 실행 한다.
    ```shell script
    (.env) $ cdk --profile=cdk_user destroy
    ```

### Useful commands

 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk docs`        open CDK documentation

## Test

1. AWS 웹 콘솔에서 Lambda 서비스를 선택한 후, `RssFeedTransBot` 람다 함수를 선택 한다.
![lambda-function-list](./assets/lambda-function-list.png)

2. **Configure test events**를 선택한다.
![lambda-configure-test-events](./assets/lambda-configure-test-events.png)

3. **Cloud Watch Scheduled Event**를 생성후 저장한다.<br/>
(이 예제에서는 `TestScheduledEvent` 라는 이름을 사용한다.)
![lambda-test-scheduled-event](./assets/lambda-test-scheduled-event.png)

4. **Test** 버튼을 클릭해서 람다 함수를 실행한다.
![lambda-run-test](./assets/lambda-run-test.png)
