package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"time"

	channel "github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go"
)

// 真机全流程测试：被动回复 + 媒体上传 + 主动发消息。
//
// 用法：DD_CLIENT_ID=... DD_CLIENT_SECRET=... go run ./example/go/fullflow
var steps int

func pass(name string) {
	steps++
	fmt.Printf("✅ PASS %s\n", name)
}

func fail(name string, err error) {
	fmt.Printf("❌ FAIL %s: %v\n", name, err)
	os.Exit(1)
}

// 8x8 红色 PNG（最小合法图片）
var tinyPNG, _ = base64.StdEncoding.DecodeString(
	"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAFklEQVR4nGP8z8Dwn4GBgYGJAQwAHxcCAmXfLkIAAAAASUVORK5CYII=",
)

func main() {
	clientID := os.Getenv("DD_CLIENT_ID")
	clientSecret := os.Getenv("DD_CLIENT_SECRET")
	if clientID == "" || clientSecret == "" {
		log.Fatal("需要环境变量 DD_CLIENT_ID / DD_CLIENT_SECRET")
	}

	ch := channel.New(channel.Config{
		ClientID:     clientID,
		ClientSecret: clientSecret,
	})

	ch.OnMessage(func(ctx context.Context, msg *channel.IncomingMessage, reply channel.Reply) error {
		fmt.Printf("   收到消息: %q from %s (%s)\n", msg.Text, msg.SenderNick, msg.ConversationType)
		pass(fmt.Sprintf("① stream 消息接收 (msgId=%s)", msg.MsgID))

		if err := reply.Text(ctx, "fullflow: 文本回复 ok"); err != nil {
			fail("② webhook 文本回复", err)
		}
		pass("② webhook 文本回复")

		s, err := reply.Stream(ctx)
		if err != nil {
			fail("③a 卡片创建/投递", err)
		}
		if !s.CardDelivered() {
			fail("③a 卡片创建/投递（降级）", fmt.Errorf("card not delivered"))
		}
		pass("③a 卡片创建+投递 (E1)")

		media, err := reply.UploadMedia(ctx, "image", "fullflow.png", "image/png", tinyPNG)
		if err != nil {
			fail("③d 媒体上传", err)
		}
		pass(fmt.Sprintf("③d 媒体上传 mediaId=%s", media.MediaID))

		content := fmt.Sprintf("# fullflow 全流程\n\n- 会话: `%s`\n- 来自: %s\n\n下面是刚上传的图片：\n\n",
			msg.ConversationType, msg.SenderNick)

		for _, r := range content {
			_ = s.Append(string(r))
			time.Sleep(10 * time.Millisecond)
		}

		if err := s.Finish(content + fmt.Sprintf("![uploaded](%s)\n", media.DownloadURL)); err != nil {
			fail("③e 流式卡片收口", err)
		}
		pass("③e 流式卡片+图片内嵌收口 (E2/E3/E9)")

		// 主动发消息（单聊）
		if err := ch.SendText(ctx, channel.SendTarget{UserID: msg.SenderStaffID}, "fullflow: 主动单聊文本 (SendText)"); err != nil {
			fail("④a 主动单聊 SendText", err)
		}
		pass("④a 主动单聊 SendText (batchSend)")

		if err := ch.SendMarkdown(ctx, channel.SendTarget{UserID: msg.SenderStaffID}, "主动通知", "**fullflow** 主动单聊 Markdown"); err != nil {
			fail("④b 主动单聊 SendMarkdown", err)
		}
		pass("④b 主动单聊 SendMarkdown")

		// 主动发消息（群聊，带 @）
		if msg.ConversationType == "group" {
			if err := ch.SendMarkdown(ctx, channel.SendTarget{
				ConversationID: msg.ConversationID,
				AtUserIds:      []string{msg.SenderStaffID},
			}, "群通知", "@你 fullflow 群发测试"); err != nil {
				fail("⑤ 群发 SendMarkdown+@", err)
			}
			pass("⑤ 群发 SendMarkdown+@")
		} else {
			fmt.Println("   （单聊会话：⑤ 群发@用例跳过——把机器人拉进群 @它 再跑一次可测）")
		}

		fmt.Printf("\n🎉 全流程完成：%d 步通过（主动消息请看钉钉会话）。\n", steps)
		return nil
	})

	fmt.Println("== fullflow(go)：给机器人发一条消息 ==")
	if err := ch.Start(context.Background()); err != nil {
		log.Fatal(err)
	}
}
