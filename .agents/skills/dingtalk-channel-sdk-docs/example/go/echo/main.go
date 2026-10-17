package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	channel "github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go"
)

// 演示 E1–E3：流式打字机回复（模拟假 LLM 逐字追加）。
// 运行：DD_CLIENT_ID=xxx DD_CLIENT_SECRET=xxx go run ./example/go/echo
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
		s, err := reply.Stream(ctx) // E1: 立即出"输入中"卡片
		if err != nil {
			return reply.Text(ctx, "echo: "+msg.Text)
		}

		answer := fmt.Sprintf("**收到：%s**\n\n- 单聊/群聊: `%s`\n- 发送者: %s\n```go\nfmt.Println(\"hello dingtalk channel\")\n```",
			msg.Text, msg.ConversationType, msg.SenderNick)

		for _, r := range answer { // 假流式
			_ = s.Append(string(r))
			time.Sleep(15 * time.Millisecond)
		}
		return s.Finish(answer) // E3: 终帧定格 Markdown
	})

	ch.OnCardAction(func(ctx context.Context, action *channel.CardAction, reply channel.Reply) error {
		return reply.Text(ctx, "按钮被点击: "+string(action.DataContent))
	})

	log.Println("channel started, waiting for messages...")
	if err := ch.Start(context.Background()); err != nil {
		log.Fatal(err)
	}
}
