# 一些钉钉原始消息样本

## 单纯图片

没有文字说明

```json
{
    "senderPlatform": "Win",
    "conversationId": "cidXxxxxx=",
    "chatbotCorpId": "dingxxxxxx",
    "chatbotUserId": "$:LWCP_v1:$xXxxxx",
    "openThreadId": "cidXxxxxx=",
    "msgId": "msgXxxx",
    "senderNick": "Xxxxx",
    "isAdmin": true,
    "senderStaffId": "0000000000-0000000000",
    "sessionWebhookExpiredTime": 1700005400000,
    "createAt": 1700000000000,
    "content": {
        "pictureDownloadCode": "EJixxxxx",
        "downloadCode": "mIoxxxxxxx"
    },
    "senderCorpId": "dingxxxxxx",
    "conversationType": "1",
    "senderId": "$:LWCP_v1:$Xxxxxx",
    "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxxxfsdfsdfsdfsdfessxxxxxx",
    "robotCode": "dingjgxxxxxxxxxxxxxxx",
    "msgtype": "picture"
}
```

## 纯文本消息

```json
{
    "senderPlatform": "Win",
    "conversationId": "cidXxxxxx=",
    "chatbotCorpId": "dingxxxxxx",
    "chatbotUserId": "$:LWCP_v1:$xXxxxx",
    "openThreadId": "cidXxxxxx=",
    "msgId": "msgXxxx",
    "senderNick": "Xxxxx",
    "isAdmin": true,
    "senderStaffId": "0000000000-0000000000",
    "sessionWebhookExpiredTime": 1700005400000,
    "createAt": 1700000000000,
    "senderCorpId": "dingxxxxxx",
    "conversationType": "1",
    "senderId": "$:LWCP_v1:$Xxxxxx",
    "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxxxfsdfsdfsdfsdfessxxxxxx",
    "text": {
        "content": "你好"
    },
    "robotCode": "dingjgxxxxxxxxxxxxxxx",
    "msgtype": "text"
}
```

## 图片加文字说明


```json
{
    "senderPlatform": "Win",
    "conversationId": "cidXxxxxx=",
    "chatbotCorpId": "dingxxxxxx",
    "chatbotUserId": "$:LWCP_v1:$xXxxxx",
    "openThreadId": "cidXxxxxx=",
    "msgId": "msgsXxxxxxx",
    "senderNick": "Xxxxx",
    "isAdmin": true,
    "senderStaffId": "0000000000-0000000000",
    "sessionWebhookExpiredTime": 1700005400000,
    "createAt": 1700000000000,
    "content": {
        "richText": [
            {
                "pictureDownloadCode": "EJiwxxxxx",
                "downloadCode": "mIoxxxxx",
                "type": "picture"
            },
            {
                "text": "\n"
            },
            {
                "text": "请解释下"
            }
        ]
    },
    "senderCorpId": "dingxxxxxx",
    "conversationType": "1",
    "senderId": "$:LWCP_v1:$Xxxxxx",
    "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxxxfsdfsdfsdfsdfessxxxxxx",
    "robotCode": "dingjgxxxxxxxxxxxxxxx",
    "msgtype": "richText"
}
```


## 单纯文件

```json
{
    "senderPlatform": "Win",
    "conversationId": "cidXxxxxx=",
    "chatbotCorpId": "dingxxxxxx",
    "chatbotUserId": "$:LWCP_v1:$xXxxxx",
    "openThreadId": "cidXxxxxx=",
    "msgId": "msgsxxxxx",
    "senderNick": "Xxxxx",
    "isAdmin": true,
    "senderStaffId": "0000000000-0000000000",
    "sessionWebhookExpiredTime": 1700005400000,
    "createAt": 1700000000000,
    "content": {
        "spaceId": "1111111111111",
        "fileName": "xxxxx.mp3",
        "downloadCode": "j7mg+lxxxxxxx",
        "fileId": "222222222222"
    },
    "senderCorpId": "dingxxxxxx",
    "conversationType": "1",
    "senderId": "$:LWCP_v1:$Xxxxxx",
    "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxxxfsdfsdfsdfsdfessxxxxxx",
    "robotCode": "dingjgxxxxxxxxxxxxxxx",
    "msgtype": "file"
}
```