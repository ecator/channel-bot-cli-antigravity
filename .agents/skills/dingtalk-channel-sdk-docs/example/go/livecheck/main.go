package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	channel "github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go"
)

// 真实钉钉联调一键验证（live check）。
//
// 用法：
//
//	DD_CLIENT_ID=ding... DD_CLIENT_SECRET=... [DD_UPLOAD_FILE=/path/img.png] \
//	  go run ./example/go/livecheck
//
// 流程：① 配置加载 ② Stream 连接 ③ 收消息 ④ 文本回复（token 链路）
// ⑤ 流式 AI 卡片全生命周期（E1–E3）⑥（可选）媒体上传。每步 PASS/FAIL。
var steps int

func pass(name string) {
	steps++
	fmt.Printf("✅ PASS %s\n", name)
}

func fail(name string, err error) {
	fmt.Printf("❌ FAIL %s: %v\n", name, err)
	fmt.Printf("完成 %d 步后失败。凭据/应用配置请核对：https://open-dev.dingtalk.com\n", steps)
	os.Exit(1)
}

func main() {
	clientID := os.Getenv("DD_CLIENT_ID")
	clientSecret := os.Getenv("DD_CLIENT_SECRET")
	if clientID == "" || clientSecret == "" {
		fmt.Fprintln(os.Stderr, "需要环境变量 DD_CLIENT_ID / DD_CLIENT_SECRET")
		os.Exit(2)
	}

	fmt.Println("== dingtalk-channel-sdk-go livecheck ==")
	cIDPrefix := clientID
	if len(cIDPrefix) > 8 {
		cIDPrefix = cIDPrefix[:8]
	}
	pass(fmt.Sprintf("config loaded (clientId=%s...)", cIDPrefix))

	ch := channel.New(channel.Config{
		ClientID:     clientID,
		ClientSecret: clientSecret,
	})

	ch.OnMessage(func(ctx context.Context, msg *channel.IncomingMessage, reply channel.Reply) error {
		fmt.Printf("   收到消息: %q from %s (%s)\n", msg.Text, msg.SenderNick, msg.ConversationType)
		pass(fmt.Sprintf("stream message received (msgId=%s)", msg.MsgID))

		if err := reply.Text(ctx, "livecheck: text reply ok"); err != nil {
			fail("text reply via sessionWebhook", err)
		}
		pass("text reply via sessionWebhook (token path verified)")

		s, err := reply.Stream(ctx)
		if err != nil {
			fail("AI card stream init", err)
		}
		if !s.CardDelivered() {
			fail("E1 卡片创建/投递（已降级文本——查 deliver 载荷/权限）", fmt.Errorf("card not delivered"))
		}
		pass("AI card created & delivered (E1)")

		content := fmt.Sprintf("# livecheck 流式验证\n\n- 单聊/群聊: `%s`\n- 来自: %s\n\n",
			msg.ConversationType, msg.SenderNick)

		uploadFile := os.Getenv("DD_UPLOAD_FILE")
		if uploadFile != "" {
			mt := "file"
			lower := strings.ToLower(uploadFile)
			if strings.HasSuffix(lower, ".png") || strings.HasSuffix(lower, ".jpg") || strings.HasSuffix(lower, ".jpeg") {
				mt = "image"
			}
			data, err := os.ReadFile(uploadFile)
			if err != nil {
				fail("read upload file", err)
			}
			media, err := reply.UploadMedia(ctx, mt, filepath.Base(uploadFile), "", data)
			if err != nil {
				fail("media upload", err)
			}
			pass(fmt.Sprintf("media upload, mediaId=%s", media.MediaID))
			if mt == "image" && media.DownloadURL != "" {
				content += fmt.Sprintf("![uploaded](%s)\n", media.DownloadURL)
			} else {
				content += fmt.Sprintf("- 上传媒体 mediaId: `%s`\n", media.MediaID)
			}
		}

		for _, r := range content {
			if err := s.Append(string(r)); err != nil {
				fail("stream append", err)
			}
			time.Sleep(15 * time.Millisecond)
		}

		if err := s.Finish(content); err != nil {
			fail("stream finish", err)
		}
		pass("AI card streaming lifecycle (E2/E3)")

		fmt.Printf("\n🎉 全部 %d 步通过：真实钉钉联调验证成功。\n", steps)
		return nil
	})

	ch.OnCardAction(func(ctx context.Context, action *channel.CardAction, reply channel.Reply) error {
		return reply.Text(ctx, "livecheck: card action received")
	})

	fmt.Println("waiting for a message — 在钉钉里给机器人发一句话...")
	if err := ch.Start(context.Background()); err != nil {
		log.Fatal(err)
	}
}
