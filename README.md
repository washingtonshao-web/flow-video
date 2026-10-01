# Flow Video

一句话出片：用你自己的 Google AI 订阅（Google Flow 里的 Omni 模型）生成视频。Claude 负责写分镜、在你已登录的 Chrome 里操作 Flow、检查画面、拼成 1080p 成片。只用订阅积分，不额外花钱。

> One sentence → finished video, using Google Flow (Omni) on your own Google AI subscription. A Claude Code plugin.

## 需要准备

| 项目 | 说明 |
|---|---|
| Windows 电脑 | Mac 版之后再出 |
| Claude 桌面版 | 需要 Claude Pro 或 Max，使用里面的 Code 功能 |
| Chrome + Claude 扩展 | 在 Chrome 应用商店搜索 “Claude”，点“添加到 Chrome”，登录 |
| Google AI 套餐 | Google AI Plus / Pro / Ultra，在 Chrome 里打开 [flow.google.com](https://flow.google.com) 能进去即可 |
| Python 3.10 以上 | 没有的话，对 Claude 说“帮我安装 Python” |
| （可选）Codex 桌面版 | 用 ChatGPT 账号登录后，关键帧由 ChatGPT 出图，画面更统一 |

ffmpeg 不用装，第一次使用时会自动下载。

## 安装（两行）

在 Claude 桌面版的 Code 里输入：

```
/plugin marketplace add washingtonshao-web/flow-video
/plugin install flow-video@flow-video
```

或者直接对 Claude 说：**“帮我安装 Flow Video 插件：github.com/washingtonshao-web/flow-video”**。

装好后重启 Claude，然后说：**“检查一下 flow-video 能不能用”**。Claude 会自检，并告诉你还差什么。

## 第一次使用

对 Claude 说，例如：**“做一个 30 秒的视频：清晨的上海外滩，电影感”**。

第一次保存视频时，Chrome 会弹出“访问本地网络”的提示，点 **允许**。只需要点这一次。

成片保存在你当前对话的工作文件夹里：

```
<日期_时间>_<标题>\
  final.mp4        成片（1080p）
  clips\           每个镜头
  keyframes\       关键帧
  review\          检查用的抽帧图
  shots.json       分镜
```

## 更新

```
/plugin marketplace update flow-video
```

## 说明

- 每段 8 秒视频约用 12 个 Flow 积分；积分不够会停下来告诉你，不会自动付费。
- 只有 Claude 能操作你的 Chrome；其他大模型可以用本插件的分镜、关键帧、检查和拼接部分。
- Flow 网页改版时插件可能需要更新，更新后执行上面的更新命令即可。
- 付费的 Gemini API 通道默认关闭，每次使用都必须由你在对话里同意。

License: MIT
