# ClaudeSwitch Locale Translation Prompt

Use this prompt when asking another AI system to translate a locale JSON file.

```text
You are translating a JSON locale file for a terminal UI tool named ClaudeSwitch.

Task:
Translate the values from locales/zh-CN.json into the target language and return one valid JSON file.

Rules:
- Preserve every JSON key exactly.
- Preserve the JSON structure exactly.
- Translate only human-readable string values.
- Do not translate command names, keyboard keys, environment variables, model names, file names, or JSON keys.
- Preserve placeholders exactly, including braces, such as {name}.
- Preserve backticked command snippets, for example `csw --list`.
- Keep product and technical terms as written unless the target language has a shorter established convention: Claude, Claude Code, ClaudeSwitch, DPAPI, Keyring, Token, Base URL, API Token.
- Localize naturally for the target language and region. Adjust idioms, humor, punctuation, and politeness level so it feels native to local developers.
- Keep UI labels short enough for narrow terminals. Prefer compact developer-facing wording over long explanatory prose.
- Preserve spacing inside button labels when the source uses leading or trailing spaces.
- In meta, keep code as the target locale code. Set order only if the language should appear in a specific position in the selector.
- Translate table.token_state as very short status labels for a 10-cell terminal column. Keep DPAPI, Keyring, and DPAPI N/A short.
- Translate status, form.token_hint, and form.errors. These strings appear in the bottom status bar, edit form hints, and validation errors.
- Translate tip_terms carefully. These terms drive Tip colors and clickable author/developer links. Keep each array short, include exact localized words or phrases that appear in tips, and do not translate the keys hot, cold, ice, or author.
- The tips array can be rewritten more freely as long as each tip stays useful, concise, and appropriate for a terminal developer tool.
- Return JSON only. Do not wrap it in Markdown.

Target language:
<write target locale here, for example en-US / ja-JP / ko-KR>

Input JSON:
<paste locales/zh-CN.json here>
```
