# GitHub Pages (docs/) の使い方

- この `docs/` フォルダは GitHub Pages の公開ルートとして使うことを想定しています。
- 置き換えるべきプレースホルダ:
  - `https://your-username.github.io/your-repo/` → 実際の GitHub Pages URL（またはカスタムドメイン）に変更
  - `https://your-streamlit-app-url` → Streamlit アプリの公開 URL
  - `YOUR_FORM_ID` → Google Form の埋め込み用 ID

デプロイ手順（簡単）:

1. 変更をコミットしてリモートに push

```bash
git add docs/
git commit -m "Add GitHub Pages landing page"
git push origin main
```

2. GitHub リポジトリの Settings → Pages で公開ソースを `Deploy from a branch` の `main` ブランチの `docs/` フォルダに設定する

3. Search Console にサイトを登録し、`sitemap.xml` を送信

補足: カスタムドメインを使う場合は DNS 設定と Search Console のドメイン所有権確認が必要です。
