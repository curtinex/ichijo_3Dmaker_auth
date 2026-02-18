# Stripe Webhook 検証手順

このドキュメントはローカルで `webhook_server.py` を使って Stripe の Webhook を検証する手順をまとめたものです。

前提
- `STRIPE_SECRET`, `STRIPE_WEBHOOK_SECRET`, `SUPA_URL`, `SUPA_SERVICE_ROLE` を環境変数または Streamlit secrets に設定しておくこと。
- `requirements.txt` の依存をインストール済みであること。

インストール

```bash
python -m venv .venv
source .venv/bin/activate    # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

ローカルで Webhook サーバーを起動

```bash
# Linux / macOS
python webhook_server.py
# Windows
python webhook_server.py
```

Stripe CLI を使った検証（推奨）

1. Stripe CLI をインストールしてログインします。https://stripe.com/docs/stripe-cli
2. ローカルの Webhook エンドポイントへイベントを転送します（`webhook_server.py` が `0.0.0.0:4242` で動作している前提）：

```bash
stripe listen --forward-to localhost:4242/webhook --events checkout.session.completed invoice.paid customer.subscription.created
```

3. 実際の Checkout フローを通す方法

- アプリのサインアップ画面で「有料プランに登録」ボタンを押し、Checkout を作成して支払いを完了します（テストカード: `4242 4242 4242 4242`）。
- Stripe CLI の `listen` が有効なら、Checkout の完了イベントがローカルサーバーに転送され、`members` テーブルに `status=active` の upsert が実行されます。

4. Stripe CLI でイベントを手動トリガーする（簡易テスト）

```bash
stripe trigger checkout.session.completed
```

注意事項
- `checkout.session.completed` のイベントに含まれるメールアドレスがない場合、`webhook_server.py` は `session.metadata.email` を参照して Supabase に保存します。Checkout 作成時に `metadata.email` を付与することをおすすめします。
- 本番環境では `SUPA_SERVICE_ROLE`（Supabase の service_role キー） を安全に管理してください。Service role キーは強力な権限を持ちます。

トラブルシューティング
- Webhook の署名検証エラーが出る場合：`STRIPE_WEBHOOK_SECRET` が正しいか確認してください。
- Supabase の upsert が失敗する場合は、`SUPA_URL` と `SUPA_SERVICE_ROLE` を確認してください。

以上です。
