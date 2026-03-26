# AI 裁切窗口预览放大设计

## 背景

当前素材准备区中的封面、书脊、封底卡片，已经支持以下交互：

- 鼠标移入时显示放大镜遮罩
- 点击后进入全屏 lightbox 预览
- 点击遮罩空白处或关闭按钮退出

AI 裁切窗口右侧同样展示了封底、书脊、封面三张实时预览图，但目前缺少同样的放大预览能力，导致用户在精修裁切线时，无法用与素材准备区一致的方式检查细节。

## 目标

将素材准备区现有的“hover 显示放大镜 + 点击全屏预览”体验，完整移植到 AI 裁切窗口中的三张预览图：

- 封底预览
- 书脊预览
- 封面预览

要求交互体验与素材准备区保持一致。

## 非目标

本次不包含以下内容：

- 不重构素材准备区已有 lightbox 实现
- 不抽取新的共享预览组件
- 不修改裁切线拖拽、缩放、保存、历史记录逻辑
- 不改动 Gemini 生图或预览图生成流程

## 方案选择

### 方案 1：在 AI 裁切弹窗内直接复用同样的交互模式（推荐）

在 `gemini-crop-dialog` 内部新增与素材准备区一致的 hover 遮罩与全屏预览状态。

**优点：**

- 改动范围最小
- 风险低，不影响父组件现有逻辑
- 弹窗内部自包含，容易验证
- 用户体验可以做到与素材准备区一致

**缺点：**

- lightbox 结构和部分样式会有少量重复

### 方案 2：抽取共享 lightbox / 图片预览组件

将素材准备区与 AI 裁切窗口统一改为共享组件。

**优点：**

- 长期维护更统一

**缺点：**

- 对当前小需求来说改动面过大
- 容易把简单需求扩展成重构

### 方案 3：AI 裁切弹窗只发出 preview 事件，由父组件复用现有 lightbox

`gemini-crop-dialog` 只负责 hover 和点击事件，真正的 lightbox 仍由 `print-workspace` 管理。

**优点：**

- 可以复用父组件现有全屏逻辑

**缺点：**

- 子组件与父组件耦合更强
- hover 交互仍需在弹窗内部单独维护
- 不如弹窗自包含方案清晰

## 最终设计

采用**方案 1**。

### 1. 修改范围

仅修改以下文件：

- `booklore-ui/src/app/modules/print-workspace/components/gemini-crop-dialog.component.ts`
- `booklore-ui/src/app/modules/print-workspace/components/gemini-crop-dialog.component.html`
- `booklore-ui/src/app/modules/print-workspace/components/gemini-crop-dialog.component.scss`

不修改：

- `booklore-ui/src/app/modules/print-workspace/components/material-slot.component.ts`
- `booklore-ui/src/app/modules/print-workspace/print-workspace.component.ts`

### 2. 交互设计

对于 AI 裁切窗口右侧三张预览图：

- 当预览图存在时，鼠标移入显示半透明遮罩
- 遮罩中央显示放大镜图标
- 鼠标样式为 `zoom-in`
- 点击后打开全屏 lightbox
- 点击遮罩空白区关闭
- 点击关闭按钮关闭

当预览图不存在、处于 placeholder 状态时：

- 不显示遮罩
- 不可点击放大

### 3. 组件内部状态

在 `GeminiCropDialogComponent` 内部新增轻量状态：

- `lightboxUrl`：当前全屏预览图片地址

以及两个简单行为：

- 打开预览：接收 `backPreviewUrl / spinePreviewUrl / frontPreviewUrl` 之一并写入 `lightboxUrl`
- 关闭预览：清空 `lightboxUrl`

由于三张预览图本身来自当前组件生成的 data URL，因此不需要额外的数据转换或父组件参与。

**状态清理时机：**

`lightboxUrl` 应在以下场景被清空：

- 用户点击 lightbox 遮罩空白区或关闭按钮
- 用户点击弹窗的"关闭"按钮（`onClose()`）
- 用户点击"保存并应用裁切"（`onSave()`）
- 用户切换历史展开图（`selectHistory()`）

这样可以避免 data URL 残留或状态不一致。

### 4. 模板结构调整

在每张预览图的 `.preview-image-box` 内补充：

- hover 遮罩层（使用 `*ngIf="backPreviewUrl"` 等条件，仅在图片存在时渲染）
- 放大镜图标（PrimeIcons 类名：`pi pi-search-plus`）
- 点击事件

并在组件模板底部补充 lightbox 遮罩结构，行为与素材准备区现有 lightbox 一致：

- 外层 overlay 负责点击空白关闭
- 内层 container 阻止冒泡
- 顶部关闭按钮负责显式关闭
- 中间展示当前选中大图

**键盘与可访问性：**

- 预览图存在时，其放大触发层必须可获得键盘焦点
- 支持按 Enter / Space 打开 lightbox
- 按 Escape 键关闭 lightbox（与素材准备区一致）
- 触发层与关闭按钮都应有明确的可见 focus 样式
- 触发层与关闭按钮应提供明确的可访问名称
- 打开 lightbox 后，焦点进入 lightbox 内部；关闭后返回到触发该预览的元素

### 5. 样式设计

样式目标是与素材准备区现有视觉尽量一致：

- 遮罩透明度、过渡动画、圆形深色图标底、白色放大镜图标
- hover 时遮罩淡入
- 预览图 hover 遮罩光标：`cursor: zoom-in`
- lightbox 遮罩光标：`cursor: zoom-out`
- 全屏预览层延续当前工作台已有 lightbox 风格

**z-index 层级：**

- AI 裁切弹窗本身：`z-index: 12000`
- 弹窗内 lightbox 遮罩：`z-index: 12500`（高于弹窗内容，低于可能的其他全局遮罩）

书脊预览虽然更窄，但仍沿用相同交互，不单独设计特殊行为。

### 6. 边界与错误处理

- 只有存在图片 URL 时才允许打开全屏预览
- 如果某张预览图触发 `onPreviewImageError(...)` 后被清空，则同步失去放大能力
- 若当前已打开 lightbox，而对应图片被清空，组件关闭或刷新时应避免残留无效状态

### 7. 验收标准

实现后需满足：

1. AI 裁切窗口中的封底、书脊、封面预览，在有图时 hover 均出现放大镜遮罩
2. 点击任意一张可进入全屏预览
3. 点击遮罩空白处或关闭按钮可退出
4. placeholder 状态下不出现放大入口
5. 不影响裁切线拖动、滚轮缩放、保存裁切、历史切换逻辑
6. 不影响素材准备区现有放大预览功能

## 测试建议

### 手工验证

1. 打开 AI 裁切窗口并确保三张预览图已生成
2. 分别 hover 封底、书脊、封面，确认出现放大镜遮罩
3. 分别点击三张图，确认都能正常全屏显示
4. 验证关闭按钮与点击空白关闭都有效
5. 切换历史展开图后再次验证三张图的放大功能
6. 拖动裁切线导致预览更新后，再次验证放大功能仍正常
7. 在某张图加载失败或为空时，确认不显示放大入口

## 实施备注

本设计优先保证“体验完全一致”而不是“代码完全复用”。在当前需求规模下，这比抽象共享组件更稳妥，也更符合最小改动原则。
