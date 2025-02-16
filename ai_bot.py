import os
import sys

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler

from linebot.v3.webhooks import MessageEvent, TextMessageContent, UserSource
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, ReplyMessageRequest
from linebot.v3.exceptions import InvalidSignatureError

from openai import AzureOpenAI

# get LINE credentials from environment variables
channel_access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
channel_secret = os.environ["LINE_CHANNEL_SECRET"]

if channel_access_token is None or channel_secret is None:
    print("Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET as environment variable.")
    sys.exit(1)

# get Azure OpenAI credentials from environment variables
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
azure_openai_model = os.getenv("AZURE_OPENAI_MODEL")

if azure_openai_endpoint is None or azure_openai_api_key is None or azure_openai_api_version is None:
    raise Exception(
        "Please set the environment variables AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_API_VERSION."
    )


handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

app = Flask(__name__)
ai = AzureOpenAI(
    azure_endpoint=azure_openai_endpoint, api_key=azure_openai_api_key, api_version=azure_openai_api_version
)


# LINEボットからのリクエストを受け取るエンドポイント
@app.route("/callback", methods=["POST"])
def callback():
    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError as e:
        abort(400, e)

    return "OK"


chat_history = []


# 　AIへのメッセージを初期化する関数
def init_chat_history():
    chat_history.clear()
    system_role = {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": "あなたは穏やかで優しい若い女性のような語り口を持つAIアシスタントです。ユーザーに優しく服装のアドバイスをします。最初に『こんにちは！今日はどんな服を着ましょうか？気温を教えてください！』と話しかけ、ユーザーの答えに応じて服装の提案を行います。",
            },
        ],
    }
    chat_history.append(system_role)


# 　返信メッセージをAIから取得する関数
def get_ai_response(from_user, text):
    # ユーザのメッセージを記録
    user_msg = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": text,
            },
        ],
    }
    chat_history.append(user_msg)

    # AIのパラメータ
    parameters = {
        "model": azure_openai_model,  # AIモデル
        "max_tokens": 100,  # 返信メッセージの最大トークン数
        "temperature": 0.7,  # 生成の多様性（0: 最も確実な回答、1: 最も多様な回答）
        "frequency_penalty": 0,  # 同じ単語を繰り返す頻度（0: 小さい）
        "presence_penalty": 0,  # すでに生成した単語を再度生成する頻度（0: 小さい）
        "stop": ["\n"],
        "stream": False,
    }

    # AIから返信を取得
    ai_response = ai.chat.completions.create(messages=chat_history, **parameters)
    res_text = ai_response.choices[0].message.content

    # AIの返信を記録
    ai_msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": res_text},
        ],
    }
    chat_history.append(ai_msg)
    return res_text

from linebot.v3.messaging import TextMessage, TemplateMessage, ButtonsTemplate, URIAction

# 服装アドバイスと画像URLを返す関数
def generate_outfit_advice(temp):
    if temp >= 25:
        return (
            "今日は暑いですね！Tシャツとショートパンツ、または軽いワンピースがおすすめです。帽子や日焼け止めも忘れずに！",
            "https://store.united-arrows.co.jp/ua_columns/yomimono/3681?srsltid=AfmBOooLIhgJ2liyjo5wap_G20E3PVvUlOcywSzIsIT8UluFSTpp0xEl"
        )
    elif 15 <= temp < 25:
        return (
            "過ごしやすい気温ですね！長袖のシャツや薄手のカーディガンとジーンズなどが良いですよ。",
            "https://store.united-arrows.co.jp/ua_columns/yomimono/317?srsltid=AfmBOor4MSa9S_UEggrvQAqcJBX3WbAdj7-vqCJptlb4LKcHUAyjIoPo"
        )
    else:
        return (
            "今日は肌寒いですね！コートやジャケットを羽織って、暖かい服装を心がけてください。",
            "https://store.united-arrows.co.jp/ua_columns/yomimono/9143?srsltid=AfmBOoo-2JWarQR3btGfbaQidUZMXHTaiCjA8QVHBVEa4ly7ux5C9nr5"
        )

# 　返信メッセージを生成する関数
def generate_response(from_user, text):
    res = []
    if text in ["リセット", "初期化", "クリア", "reset", "clear"]:
        # チャット履歴を初期化
        init_chat_history()
        res = [TextMessage(text="チャットをリセットしました。こんにちは！今日はどんな服を着ましょうか？気温が何℃（半角数字のみ）か教えてください！")]
    elif text.isdigit():  # 気温が入力された場合
        temp = int(text)
        advice, homepage_url = generate_outfit_advice(temp)  # アドバイスとサイトURLを取得

        # 服装アドバイスのテキストメッセージ
        text_message = TextMessage(text=advice)

        # サイトのリンクをボタン付きで送る
        buttons_template = ButtonsTemplate(
            text="おすすめのコーデをチェック！",
            actions=[URIAction(label="コーデを見る", uri=homepage_url)]
        )
        link_message = TemplateMessage(alt_text="おすすめの服装を見るボタン", template=buttons_template)

        res = [text_message, link_message]
    else:
        # AIを使って返信を生成
        res = [TextMessage(text=get_ai_response(from_user, text))]
    return res


# メッセージを受け取った時の処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    # 送られてきたメッセージを取得
    text = event.message.text

    # 返信メッセージの送信
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        res = []
        if isinstance(event.source, UserSource):
            # ユーザー情報が取得できた場合
            profile = line_bot_api.get_profile(event.source.user_id)
            # 返信メッセージを生成
            res = generate_response(profile.display_name, text)
        else:
            # ユーザー情報が取得できなかった場合
            # fmt: off
            # 定型文の返信メッセージ
            res = [
                TextMessage(text="ユーザー情報を取得できませんでした。"),
                TextMessage(text=f"メッセージ：{text}")
            ]
            # fmt: on

        # メッセージを送信
        line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=res))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
