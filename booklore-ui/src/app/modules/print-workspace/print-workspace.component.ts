/*
============================================================
Booklore Print Workspace Component
版本：V1.9

修复内容（相较 V1.8）：

1 generatePdf() 完整实现
  - 检查 workspace.pdf_path 是否已存在
  - 有则直接跳转查看；无则调用生成接口
  - 携带完整参数（trim_size / page_count 等）
  - 生成中显示 loading 状态，禁用按钮
  - 生成成功后新页签打开 PDF 查看页

2 新增 pdfGenerating / pdfError 状态字段
============================================================
*/

import { Component, OnInit, OnDestroy, HostListener, ChangeDetectorRef, ViewChild, ElementRef } from "@angular/core";
import { Subscription } from "rxjs";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { Router, ActivatedRoute } from "@angular/router";

import { WorkspaceStateService } from "./services/workspace-state.service";
import { PreviewEngineService } from "./services/preview-engine.service";
import {
  PrintService,
  WorkspaceState,
  PrintRequest,
} from "./services/print.service";
import { MaterialService } from "./services/material.service";

import { MaterialSlotComponent } from "./components/material-slot.component";
import { TrimSize } from "./models/workspace.model";

@Component({
  selector: "app-print-workspace",
  standalone: true,
  imports: [FormsModule, CommonModule, MaterialSlotComponent],
  templateUrl: "./print-workspace.component.html",
  styleUrls: ["./print-workspace.component.scss"],
})
export class PrintWorkspaceComponent implements OnInit, OnDestroy {
  bookId = 0;

  @ViewChild('aiLogContent', { static: false }) aiLogContent?: ElementRef;

  private compositeCache = new Map<string, string>();
  private wsSub?: Subscription;
  compositeUrl = "";
  lightboxUrl = "";

  /** [V1.9] PDF 生成中状态 */
  pdfGenerating = false;

  /** [V1.9] PDF 生成错误信息 */
  pdfError = "";

  /** PDF尺寸信息 */
  pdfSizeInfo = {
    width: 0,
    height: 0,
    orientation: '未知',
    matchedSize: null as 'A4' | 'A5' | 'B5' | null,
    loading: true,
    error: ''
  };

  /** PDF格式化状态 */
  resizing = false;
  resizeProgress = 0;
  resizeStage = '';
  resizeLogs: string[] = [];

  // ── AI 统一生成状态 ──────────────────────────────────────────
  aiGenerating = false;
  aiProgressText = "AI 生成书脊 & 封底";
  aiLastResult: "success" | "error" | null = null;
  aiErrorMsg = "";

  get canAiGenerate(): boolean {
    return !!this.workspace?.cover?.selected;
  }

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    public workspaceState: WorkspaceStateService,
    private preview: PreviewEngineService,
    private print: PrintService,
    public material: MaterialService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get("bookId");
    this.bookId = id ? Number(id) : 0;
    if (!this.bookId) {
      console.error("PrintWorkspace: bookId 无效");
      return;
    }

    // 订阅 workspace$ — 素材上传/删除/选择后后端返回新 ws，
    // setWorkspace() 触发这里，自动清缓存并刷新拼版预览
    this.wsSub = this.workspaceState.workspace$.subscribe((ws) => {
      if (!ws) return;
      this.compositeCache.clear();
      this.refreshComposite();
      // 强制触发变更检测，确保历史预览图可以正常切换
      this.cdr.detectChanges();
    });

    this.initWorkspace();
    this.loadPdfInfo();
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  private initWorkspace(): void {
    this.print.initWorkspace(this.bookId).subscribe({
      next: (ws) => {
        this.workspaceState.setWorkspace(ws);
        this.refreshComposite();
      },
      error: (err) => console.error("Workspace 初始化失败", err),
    });
  }

  get workspace(): WorkspaceState | null {
    return this.workspaceState.workspace;
  }

  get workspaceViewModel() {
    const ws = this.workspace;
    if (!ws) return null;
    return {
      bookName: ws.book_name,
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
      spineWidth: ws.spine_width_mm,
      cover: {
        selected: ws.cover?.selected ?? null,
        url: this.material.getAssetUrl(
          this.bookId,
          "cover",
          ws.cover?.selected ?? "",
        ),
        history: ws.cover?.history ?? [],
      },
      spine: {
        selected: ws.spine?.selected ?? null,
        url: this.material.getAssetUrl(
          this.bookId,
          "spine",
          ws.spine?.selected ?? "",
        ),
        history: ws.spine?.history ?? [],
      },
      back: {
        selected: ws.back?.selected ?? null,
        url: this.material.getAssetUrl(
          this.bookId,
          "back",
          ws.back?.selected ?? "",
        ),
        history: ws.back?.history ?? [],
      },
    };
  }

  get previewPages(): string[] {
    const ws = this.workspace;
    if (!ws) return [];

    const coverUrl = ws.cover?.selected
      ? this.material.getAssetUrl(this.bookId, "cover", ws.cover.selected)
      : "";
    const spineUrl = ws.spine?.selected
      ? this.material.getAssetUrl(this.bookId, "spine", ws.spine.selected)
      : "";
    const backUrl = ws.back?.selected
      ? this.material.getAssetUrl(this.bookId, "back", ws.back.selected)
      : "";

    if (ws.trim_size === "A4") {
      return [coverUrl, spineUrl, backUrl];
    }

    const firstPage = this.compositeUrl || coverUrl;
    return [firstPage, backUrl];
  }

  refreshComposite(): void {
    const ws = this.workspace;
    if (!ws || ws.trim_size === "A4") {
      this.compositeUrl = "";
      return;
    }

    const coverUrl = ws.cover?.selected
      ? this.material.getAssetUrl(this.bookId, "cover", ws.cover.selected)
      : "";
    const spineUrl = ws.spine?.selected
      ? this.material.getAssetUrl(this.bookId, "spine", ws.spine.selected)
      : "";

    if (!coverUrl) {
      this.compositeUrl = "";
      return;
    }

    const cacheKey = `${coverUrl}|${spineUrl}|${ws.spine_width_mm}`;
    if (this.compositeCache.has(cacheKey)) {
      this.compositeUrl = this.compositeCache.get(cacheKey)!;
      return;
    }

    const pageW = this.preview.getPageWidth(ws as any);
    const pageH = this.preview.getPageHeight(ws as any);
    const spineW = ws.spine_width_mm ?? 0;

    const CANVAS_H = 400;
    const scale = CANVAS_H / pageH;
    const coverPx = Math.round(pageW * scale);
    // 无书脊素材时 spinePx = 0，canvas 只包含封面，不画任何书脊痕迹
    const spinePx = spineUrl ? Math.max(Math.round(spineW * scale), 2) : 0;
    const totalW = coverPx + spinePx;

    const canvas = document.createElement("canvas");
    canvas.width = totalW;
    canvas.height = CANVAS_H;
    const ctx = canvas.getContext("2d")!;

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, totalW, CANVAS_H);

    const loadImage = (url: string): Promise<HTMLImageElement> =>
      new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = url;
      });

    const promises: Promise<HTMLImageElement | null>[] = [
      loadImage(coverUrl),
      spineUrl ? loadImage(spineUrl).catch(() => null) : Promise.resolve(null),
    ];

    Promise.all(promises)
      .then(([coverImg, spineImg]) => {
        if (!coverImg) return;
        // 印刷标准展开图：书脊在左，封面在右（与 PDF 生成顺序一致）
        if (spineImg && spinePx > 0) {
          ctx.drawImage(spineImg, 0, 0, spinePx, CANVAS_H);
          ctx.drawImage(coverImg, spinePx, 0, coverPx, CANVAS_H);
        } else {
          ctx.drawImage(coverImg, 0, 0, coverPx, CANVAS_H);
        }
        const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
        this.compositeCache.set(cacheKey, dataUrl);
        this.compositeUrl = dataUrl;
      })
      .catch(() => {
        this.compositeUrl = coverUrl;
      });
  }

  setTrim(size: TrimSize) {
    this.workspaceState.setTrim(size);
    this.workspaceState.recalcSpine();
    const ws = this.workspace as any;
    if (ws) ws.pdf_path = null;
    this.refreshComposite();
    this.saveParams();
  }

  recalculateSpine() {
    this.workspaceState.recalcSpine();
    const ws = this.workspace as any;
    if (ws) ws.pdf_path = null;
    this.saveParams();
    this.compositeCache.clear();
    this.refreshComposite();
  }

  getPageHeight(): number {
    if (!this.workspace) return 0;
    return this.preview.getPageHeight(this.workspace as any);
  }

  getPageRatio(): string {
    if (!this.workspace) return "1/1";
    return this.preview.getPageRatio(this.workspace as any);
  }

  getPreviewPageRatio(index: number): string {
    if (!this.workspace) return "1/1";
    const w = this.preview.getPreviewPageWidth(this.workspace as any, index);
    const h = this.preview.getPageHeight(this.workspace as any);
    return `${w}/${h}`;
  }

  getPreviewPageWidth(index: number): number {
    if (!this.workspace) return 0;
    return this.preview.getPreviewPageWidth(this.workspace as any, index);
  }

  trackPreview(index: number, item: string) {
    return item;
  }

  openLightbox(url: string) {
    if (url) this.lightboxUrl = url;
  }
  closeLightbox() {
    this.lightboxUrl = "";
  }

  /** 素材删除：用服务端返回的最新 workspace 更新状态，避免幽灵文件 */
  onMaterialDeleted(ws: WorkspaceState) {
    this.workspaceState.setWorkspace(ws);
  }

  /** 素材上传：清除旧 PDF 标记（预览刷新由 workspace$ 订阅自动触发） */
  onMaterialUploaded() {
    const ws = this.workspace as any;
    if (ws) ws.pdf_path = null;
  }

  @HostListener("document:keydown.escape")
  onEsc() {
    this.closeLightbox();
  }

  /**
   * ============================================================
   * [V1.9] generatePdf — 完整实现
   *
   * 流程：
   * 1 检查 workspace.pdf_path 是否已存在
   *   → 有：直接新页签打开查看页
   *   → 无：调用生成接口，携带完整参数
   * 2 生成中显示 loading，禁用按钮
   * 3 生成成功后新页签打开查看页
   * 4 生成失败显示错误提示
   * ============================================================
   */
  generatePdf() {
    const ws = this.workspace;
    if (!ws) return;

    if ((ws as any).pdf_path) {
      this.openPdfViewer();
      return;
    }

    if (!ws.cover?.selected || !ws.spine?.selected || !ws.back?.selected) {
      this.pdfError = "请先在素材准备区选择封面、书脊、封底素材";
      setTimeout(() => (this.pdfError = ""), 4000);
      return;
    }

    this.pdfGenerating = true;
    this.pdfError = "";

    const request: PrintRequest = {
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
    };

    this.print.generatePdf(this.bookId, request).subscribe({
      next: (result) => {
        this.pdfGenerating = false;
        this.workspaceState.setWorkspace(result);
        this.openPdfViewer();
      },
      error: (err) => {
        this.pdfGenerating = false;
        this.pdfError = "PDF 生成失败，请检查素材是否完整";
        console.error("PDF 生成失败", err);
        setTimeout(() => (this.pdfError = ""), 5000);
      },
    });
  }

  // ─────────────────────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════
  // AI 生成相关
  // ══════════════════════════════════════════════════════════════

  aiProgress = 0;
  aiPhaseText = "";
  aiTotalTokens = 0;
  aiLogMessages: Array<{
    time: string;
    percent: number;
    message: string;
    highlight?: boolean;
  }> = [];

  /**
   * 添加日志条目并自动滚动到底部
   *
   * @param message 日志消息
   * @param percent 当前进度百分比
   * @param highlight 是否高亮显示（用于重要节点）
   */
  private addLog(message: string, percent: number, highlight = false): void {
    const now = new Date();
    const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

    this.aiLogMessages.push({ time, percent, message, highlight });
    this.cdr.detectChanges();

    // 延迟滚动确保 DOM 已更新
    setTimeout(() => {
      const element = this.aiLogContent?.nativeElement;
      if (element) {
        element.scrollTop = element.scrollHeight;
      }
    }, 50);
  }

  /**
   * 清空日志记录
   */
  clearLogs(): void {
    this.aiLogMessages = [];
  }

  /**
   * 启动 AI 生成任务（书脊 + 封底）
   */
  async onAiGenerate(): Promise<void> {
    // 防止重复点击
    if (!this.canAiGenerate || this.aiGenerating) {
      return;
    }

    // 初始化状态
    this.aiGenerating = true;
    this.aiLastResult = null;
    this.aiErrorMsg = "";
    this.aiProgress = 0;
    this.aiProgressText = "AI 生成中...";
    this.aiPhaseText = "准备中";
    this.aiTotalTokens = 0;
    this.aiLogMessages = [];
    this.addLog("开始AI生成任务...", 0, true);

    const ws = this.workspace;
    if (!ws) {
      this.handleAiError("workspace 未初始化");
      return;
    }

    const request = {
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
      target: "all",
    };

    try {
      await this._runAllWithSse(request as any);
      this.handleAiSuccess();
    } catch (error: unknown) {
      this.handleAiError(this.extractErrorMessage(error));
    } finally {
      this.aiGenerating = false;
      // 3秒后恢复按钮文字
      setTimeout(() => {
        this.aiProgressText = "AI 生成书脊 & 封底";
        if (this.aiLastResult === "success") {
          this.aiPhaseText = "";
        }
      }, 3000);
    }
  }

  /**
   * 处理 AI 生成成功
   */
  private handleAiSuccess(): void {
    this.aiLastResult = "success";
    this.aiProgress = 100;
    this.aiPhaseText = this.aiTotalTokens > 0
      ? `✅ 生成完成！消耗 ${this.aiTotalTokens} Tokens`
      : "✅ 生成完成！";
  }

  /**
   * 处理 AI 生成错误
   */
  private handleAiError(message: string): void {
    this.aiLastResult = "error";
    this.aiErrorMsg = message;
    this.aiGenerating = false;
    console.error("[AI Generate] 失败:", message);
  }

  /**
   * 提取错误消息
   */
  private extractErrorMessage(error: unknown): string {
    if (error && typeof error === 'object' && 'message' in error) {
      return (error as { message: string }).message;
    }
    return "网络异常，请检查服务器连接";
  }

  /**
   * 执行 AI 生成任务（SSE 流式接收进度）
   */
  private _runAllWithSse(request: any): Promise<void> {
    return new Promise((resolve, reject) => {
      this.print.aiGenerateStart(this.bookId, "all", request).subscribe({
        next: (res: any) => {
          if (!res?.task_id) {
            reject(new Error("未获取到任务ID"));
            return;
          }

          const taskId = res.task_id;
          // 直连 print-engine SSE 端口（5800），避免 nginx 超时
          const pythonBase = `${window.location.protocol}//${window.location.hostname}:5800`;
          const url = `${pythonBase}/workspace/ai-generate/progress/${taskId}`;
          const es = new EventSource(url);

          es.onmessage = (event: MessageEvent) => {
            try {
              const data = JSON.parse(event.data);

              this.handleSseMessage(data, es, resolve, reject);
            } catch (e) {
              es.close();
              reject(e);
            }
          };

          es.onerror = () => {
            // 心跳触发的 onerror 忽略，只处理真正的连接断开
            if (es.readyState === EventSource.CLOSED) {
              es.close();
              reject(new Error("SSE 连接断开"));
            }
          };
        },
        error: (err: any) => {
          const msg = err?.error?.error ?? err?.error?.message ?? err?.message ?? "AI 生成请求失败";
          reject(new Error(msg));
        },
      });
    });
  }

  /**
   * 处理 SSE 消息
   */
  private handleSseMessage(
    data: any,
    es: EventSource,
    resolve: () => void,
    reject: (error: Error) => void
  ): void {
    // 更新进度
    if (data.pct !== undefined) {
      this.aiProgress = data.pct;
    }

    // 更新 Token 消耗
    if (data.total_tokens !== undefined) {
      this.aiTotalTokens = data.total_tokens;
    }

    // 更新阶段文字并记录日志
    if (data.stage) {
      this.aiPhaseText = data.stage;
      const isHighlight =
        data.stage.includes('【') ||
        data.pct === 0 ||
        data.pct === 50 ||
        data.pct === 100;
      this.addLog(data.stage, data.pct || 0, isHighlight);
    } else if (data.phase === "spine") {
      this.aiPhaseText = "生成书脊中...";
    } else if (data.phase === "back") {
      this.aiPhaseText = "生成封底中...";
    }

    // 触发变更检测
    this.cdr.detectChanges();

    // 处理完成状态
    if (data.status === "done") {
      es.close();
      this.addLog("✅ 所有任务完成！", 100, true);

      if (data.ws) {
        this.workspaceState.setWorkspace(data.ws);
        this.compositeCache.clear();
        this.refreshComposite();
        // 强制触发变更检测，确保历史预览图可以正常切换
        this.cdr.detectChanges();
      }

      if (data.total_tokens !== undefined) {
        this.aiTotalTokens = data.total_tokens;
        this.addLog(`总计消耗 ${data.total_tokens} tokens`, 100);
      }

      this.aiProgress = 100;
      resolve();
    } else if (data.status === "error") {
      es.close();
      this.addLog(`❌ 生成失败: ${data.error ?? "未知错误"}`, data.pct || 0, true);
      reject(new Error(data.error ?? "AI 生成失败"));
    }
  }

  /** 跳转到官方 PDF 阅读器（print 模式） */
  /**
   * 预览PDF
   */
  previewPdf(): void {
    this.router.navigate(["/pdf-reader", "print", this.bookId]);
  }

  private openPdfViewer() {
    this.router.navigate(["/pdf-reader", "print", this.bookId]);
  }

  generatePdfFromViewer() {
    const ws = this.workspace;
    if (!ws) return;
    const request: PrintRequest = {
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
    };
    return this.print.generatePdf(this.bookId, request);
  }

  /**
   * 持久化当前成书参数到后端（暂不实现，print.service 无对应接口）
   */
  private saveParams(): void {
    // TODO: 待 print.service 新增 saveWorkspaceParams 接口后实现
  }

  goBookDetail() {
    this.router.navigate(["/book", this.bookId]);
  }
  goLibrary() {
    this.router.navigate(["/all-books"]);
  }

  /**
   * 加载PDF尺寸信息
   * 从后端获取电子书PDF的实际尺寸
   */
  private loadPdfInfo(): void {
    this.pdfSizeInfo.loading = true;
    this.pdfSizeInfo.error = '';

    this.print.getPdfInfo(this.bookId).subscribe({
      next: (result) => {
        if (result.success && result.data) {
          const data = result.data;
          this.pdfSizeInfo = {
            width: Math.round(data.width_mm),
            height: Math.round(data.height_mm),
            orientation: this.translateOrientation(data.orientation),
            matchedSize: this.matchStandardSize(data.width_mm, data.height_mm),
            loading: false,
            error: ''
          };
        } else {
          this.pdfSizeInfo = {
            width: 0,
            height: 0,
            orientation: '未知',
            matchedSize: null,
            loading: false,
            error: result.error || 'PDF文件不存在'
          };
        }
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.pdfSizeInfo = {
          width: 0,
          height: 0,
          orientation: '未知',
          matchedSize: null,
          loading: false,
          error: '获取PDF信息失败'
        };
        this.cdr.detectChanges();
      }
    });
  }

  /**
   * 翻译方向
   */
  private translateOrientation(orientation: string): string {
    const map: Record<string, string> = {
      'portrait': '竖向',
      'landscape': '横向',
      'square': '正方形'
    };
    return map[orientation] || '未知';
  }

  /**
   * 格式化PDF
   */
  onResizePdf(): void {
    if (this.resizing) return;

    // 重置日志
    this.resizeLogs = [];

    // 弹出尺寸选择对话框
    const targetSize = this.showSizeSelector();
    if (!targetSize) {
      return;
    }

    // 确认对话框
    const confirmed = confirm(
      `确认要将PDF格式化为${targetSize}尺寸吗？\n\n` +
      `系统会先备份原文件，确保安全。\n` +
      `格式化过程可能需要几分钟，请耐心等待。`
    );

    if (!confirmed) {
      return;
    }

    this.resizing = true;
    this.resizeProgress = 0;
    this.resizeStage = '准备中...';
    this.addResizeLog(`启动 ${targetSize} 格式化...`);

    // 启动格式化任务
    this.print.resizePdf(this.bookId, targetSize).subscribe({
      next: (result) => {
        if (!result.task_id) {
          this.addResizeLog('❌ 启动失败');
          this.handleResizeError('启动格式化任务失败');
          return;
        }

        this.addResizeLog(`✓ 任务ID: ${result.task_id.substring(0, 8)}...`);

        // 监听进度
        this.watchResizeProgress(result.task_id);
      },
      error: (err) => {
        this.addResizeLog(`❌ ${err.error?.error || '启动失败'}`);
        this.handleResizeError(err.error?.error || '启动失败');
      }
    });
  }

  /**
   * 显示尺寸选择对话框
   */
  private showSizeSelector(): 'A4' | 'A5' | 'B5' | null {
    const choice = prompt(
      '请选择目标尺寸：\n\n' +
      '1 - A4 (210×297mm)\n' +
      '2 - A5 (148×210mm)\n' +
      '3 - B5 (176×250mm)\n\n' +
      '请输入数字 1-3：'
    );

    const map: Record<string, 'A4' | 'A5' | 'B5'> = {
      '1': 'A4',
      '2': 'A5',
      '3': 'B5'
    };

    return map[choice || ''] || null;
  }

  /**
   * 监听格式化进度
   */
  private watchResizeProgress(taskId: string): void {
    const pythonBase = `${window.location.protocol}//${window.location.hostname}:5800`;
    const url = `${pythonBase}/pdf/resize/progress/${taskId}`;

    const es = new EventSource(url);

    es.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);

        this.resizeProgress = data.progress || 0;
        this.resizeStage = data.stage || '';

        // 只记录关键进度节点
        if (data.progress === 10 || data.progress === 50 || data.progress === 90) {
          this.addResizeLog(`${data.stage}`);
        }

        if (data.status === 'done') {
          es.close();
          this.resizing = false;
          this.resizeProgress = 100;

          // 检查是否跳过（已经是目标尺寸）
          if (data.skipped) {
            this.addResizeLog('✓ 已是目标尺寸，跳过');
            alert(data.message || 'PDF已经是目标尺寸，无需格式化');
          } else {
            this.addResizeLog('✓ 完成');
            if (data.new_size) {
              this.addResizeLog(`新尺寸: ${data.new_size.width_mm}×${data.new_size.height_mm}mm`);
            }

            // 格式化完成后跳转到预览页面
            const shouldPreview = confirm('PDF格式化完成！是否立即预览？');
            if (shouldPreview) {
              this.previewPdf();
            }
          }

          // 刷新PDF尺寸信息
          setTimeout(() => {
            this.loadPdfInfo();
          }, 500);
        } else if (data.status === 'error') {
          es.close();
          const errorMsg = data.error || '未知错误';
          // 提取关键错误信息
          const shortError = errorMsg.includes('第') ? errorMsg.split('详细信息')[0].trim() : errorMsg;
          this.addResizeLog(`❌ ${shortError}`);
          this.handleResizeError(errorMsg);
        }

        this.cdr.detectChanges();
      } catch (e) {
        es.close();
        this.addResizeLog(`❌ 数据解析失败`);
        this.handleResizeError('解析进度数据失败');
      }
    };

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        es.close();
        this.addResizeLog('❌ 连接中断');
        this.handleResizeError('连接中断');
      }
    };
  }

  /**
   * 处理格式化错误
   */
  private handleResizeError(message: string): void {
    this.resizing = false;
    this.resizeProgress = 0;
    this.resizeStage = '';
    alert(`格式化失败：${message}`);
    this.cdr.detectChanges();
  }

  /**
   * 添加格式化日志
   */
  private addResizeLog(message: string): void {
    const timestamp = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    this.resizeLogs.push(`${timestamp} ${message}`);
    // 限制日志数量，避免过长
    if (this.resizeLogs.length > 10) {
      this.resizeLogs.shift();
    }
    this.cdr.detectChanges();
  }

  /**
   * 更新PDF尺寸信息（已废弃，改用loadPdfInfo）
   * 根据当前trim_size计算物理尺寸、方向和匹配的标准尺寸
   */
  private updatePdfSizeInfo(): void {
    // 此方法已废弃，保留以兼容旧代码
    // 现在使用loadPdfInfo()从后端获取实际PDF尺寸
  }

  /**
   * 匹配标准尺寸
   * @param width 宽度（mm）
   * @param height 高度（mm）
   * @returns 匹配的标准尺寸或null
   */
  private matchStandardSize(width: number, height: number): 'A4' | 'A5' | 'B5' | null {
    const TOLERANCE = 2; // 容差2mm
    const sizes: Record<'A4' | 'A5' | 'B5', [number, number]> = {
      A4: [210, 297],
      A5: [148, 210],
      B5: [176, 250]
    };

    for (const [name, [w, h]] of Object.entries(sizes) as Array<['A4' | 'A5' | 'B5', [number, number]]>) {
      // 考虑横向和竖向
      if (
        (Math.abs(width - w) <= TOLERANCE && Math.abs(height - h) <= TOLERANCE) ||
        (Math.abs(width - h) <= TOLERANCE && Math.abs(height - w) <= TOLERANCE)
      ) {
        return name;
      }
    }
    return null;
  }
}
