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
  AiCropHistoryItem,
} from "./services/print.service";
import { MaterialService } from "./services/material.service";

import { MaterialSlotComponent } from "./components/material-slot.component";
import { GeminiConfigDialogComponent } from "./components/gemini-config-dialog.component";
import { GeminiCropDialogComponent } from "./components/gemini-crop-dialog.component";
import { TrimSize, SpreadPreviewItem } from "./models/workspace.model";
import { calcSpineWidth } from "./utils/dimension.util";

interface WorkspaceViewModel {
  bookName?: string;
  trimSize: TrimSize;
  pageCount: number;
  paperThickness: number;
  spineWidth: number;
  cover: {
    selected: string | null;
    url: string;
    history: Array<{
      filename: string;
      type: "cover" | "front_output";
      label: string;
      active: boolean;
    }>;
    statusBadge: string;
    usingFrontOutput: boolean;
  };
  frontOutput: {
    selected: string | null;
    url: string;
  };
  spine: {
    selected: string | null;
    url: string;
    history: string[];
  };
  back: {
    selected: string | null;
    url: string;
    history: string[];
  };
}

interface AiGenerateAllRequest {
  trimSize: TrimSize;
  pageCount: number;
  paperThickness: number;
  target: "all";
}

@Component({
  selector: "app-print-workspace",
  standalone: true,
  imports: [FormsModule, CommonModule, MaterialSlotComponent, GeminiConfigDialogComponent, GeminiCropDialogComponent],
  templateUrl: "./print-workspace.component.html",
  styleUrls: ["./print-workspace.component.scss"],
})
export class PrintWorkspaceComponent implements OnInit, OnDestroy {
  bookId = 0;

  @ViewChild('aiLogContent', { static: false }) aiLogContent?: ElementRef;

  private compositeCache = new Map<string, string>();
  private compositeRenderToken = 0;
  private wsSub?: Subscription;
  private lastWorkspaceRef: WorkspaceState | null = null;
  private workspaceViewModelCache: WorkspaceViewModel | null = null;
  private previewPagesCache: string[] = [];
  private compositeCacheKey = '';
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
  resizeDoubleCount = 0;  // 双页计数
  resizeSingleCount = 0;  // 单页计数
  resizeErrorCount = 0;   // 错误计数

  // ── AI 统一生成状态 ──────────────────────────────────────────
  aiGenerating = false;
  aiProgressText = "AI 生成书脊 & 封底";
  aiLastResult: "success" | "error" | null = null;
  aiErrorMsg = "";

  // Gemini 配置与裁切弹窗状态
  aiConfigVisible = false;
  aiCropVisible = false;
  aiConfigLoading = false;
  aiConfigBundle: { runtime: any; prompts: any } | null = null;
  cropSaving = false;
  spreadHistory: SpreadPreviewItem[] = [];
  spreadPreview: SpreadPreviewItem | null = null;

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
      this.lastWorkspaceRef = ws;
      this.workspaceViewModelCache = null;
      this.previewPagesCache = [];
      this.compositeCacheKey = '';
      this.refreshComposite();
      this.syncSpreadHistoryFromWorkspace(ws);
      this.syncSpreadPreviewWithHistory();
    });

    this.initWorkspace();
    this.loadPdfInfo();

    // 恢复上次格式化日志（如果有）
    this.restoreResizeLogs();
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  private initWorkspace(): void {
    this.print.initWorkspace(this.bookId).subscribe({
      next: (ws) => {
        this.workspaceState.setWorkspace(ws);
      },
      error: (err) => console.error("Workspace 初始化失败", err),
    });
  }

  get workspace(): WorkspaceState | null {
    return this.workspaceState.workspace;
  }

  get workspaceViewModel(): WorkspaceViewModel | null {
    const ws = this.workspace;
    if (!ws) return null;
    if (this.workspaceViewModelCache && this.lastWorkspaceRef === ws) {
      return this.workspaceViewModelCache;
    }

    const coverHistory = ws.cover?.history ?? [];
    const frontOutputHistory = ws.front_output?.history ?? [];
    const effectiveFront = this.material.getEffectiveFrontSelection(this.bookId, ws);
    const effectiveFrontSelected = effectiveFront.selected;
    const effectiveFrontUrl = effectiveFront.url;
    const coverSelected = ws.cover?.selected ?? null;
    const mergedCoverHistory = [
      ...coverHistory.map((filename) => ({
        filename,
        type: 'cover' as const,
        label: '原图',
        active: effectiveFrontSelected === filename,
      })),
      ...frontOutputHistory.map((filename) => ({
        filename,
        type: 'front_output' as const,
        label: '裁切',
        active: effectiveFrontSelected === filename,
      })),
    ];

    this.workspaceViewModelCache = {
      bookName: ws.book_name,
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
      spineWidth: ws.spine_width_mm,
      cover: {
        selected: effectiveFrontSelected,
        url: effectiveFrontUrl,
        history: mergedCoverHistory,
        statusBadge: effectiveFront.usingFrontOutput ? '当前输出' : '',
        usingFrontOutput: effectiveFront.usingFrontOutput,
      },
      frontOutput: {
        selected: effectiveFrontSelected,
        url: effectiveFrontUrl,
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

    return this.workspaceViewModelCache;
  }

  get previewPages(): string[] {
    const ws = this.workspace;
    if (!ws) return [];
    if (this.previewPagesCache.length && this.lastWorkspaceRef === ws && this.compositeCacheKey === this.compositeUrl) {
      return this.previewPagesCache;
    }

    const vm = this.workspaceViewModel;
    if (!vm) {
      return [];
    }

    const spineUrl = ws.spine?.selected
      ? this.material.getAssetUrl(this.bookId, "spine", ws.spine.selected)
      : "";
    const backUrl = ws.back?.selected
      ? this.material.getAssetUrl(this.bookId, "back", ws.back.selected)
      : "";

    if (ws.trim_size === "A4") {
      this.previewPagesCache = [vm.cover.url, spineUrl, backUrl];
      this.compositeCacheKey = this.compositeUrl;
      return this.previewPagesCache;
    }

    const firstPage = this.compositeUrl || vm.cover.url;
    this.previewPagesCache = [firstPage, backUrl];
    this.compositeCacheKey = this.compositeUrl;
    return this.previewPagesCache;
  }

  refreshComposite(): void {
    const renderToken = ++this.compositeRenderToken;
    const ws = this.workspace;
    if (!ws || ws.trim_size === "A4") {
      this.compositeUrl = "";
      this.compositeCacheKey = this.compositeUrl;
      this.previewPagesCache = [];
      return;
    }

    const effectiveFront = this.material.getEffectiveFrontSelection(this.bookId, ws);
    const effectiveFrontUrl = effectiveFront.url;
    const spineUrl = ws.spine?.selected
      ? this.material.getAssetUrl(this.bookId, "spine", ws.spine.selected)
      : "";

    if (!effectiveFrontUrl) {
      this.compositeUrl = "";
      this.compositeCacheKey = this.compositeUrl;
      this.previewPagesCache = [];
      return;
    }

    const cacheKey = `${effectiveFrontUrl}|${spineUrl}|${ws.spine_width_mm}`;
    if (this.compositeCache.has(cacheKey)) {
      this.compositeUrl = this.compositeCache.get(cacheKey)!;
      this.compositeCacheKey = this.compositeUrl;
      this.previewPagesCache = [];
      return;
    }

    const pageW = this.preview.getPageWidth(ws);
    const pageH = this.preview.getPageHeight(ws);
    const spineW = ws.spine_width_mm ?? 0;

    const CANVAS_H = 400;
    const scale = CANVAS_H / pageH;
    const coverPx = Math.round(pageW * scale);
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
      loadImage(effectiveFrontUrl),
      spineUrl ? loadImage(spineUrl).catch(() => null) : Promise.resolve(null),
    ];

    Promise.all(promises)
      .then(([coverImg, spineImg]) => {
        if (renderToken !== this.compositeRenderToken || !coverImg) return;
        if (spineImg && spinePx > 0) {
          ctx.drawImage(spineImg, 0, 0, spinePx, CANVAS_H);
          ctx.drawImage(coverImg, spinePx, 0, coverPx, CANVAS_H);
        } else {
          ctx.drawImage(coverImg, 0, 0, coverPx, CANVAS_H);
        }
        const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
        this.compositeCache.set(cacheKey, dataUrl);
        this.compositeUrl = dataUrl;
        this.compositeCacheKey = this.compositeUrl;
        this.previewPagesCache = [];
      })
      .catch(() => {
        if (renderToken !== this.compositeRenderToken) return;
        this.compositeUrl = effectiveFrontUrl;
        this.compositeCacheKey = this.compositeUrl;
        this.previewPagesCache = [];
      });
  }

  setTrim(size: TrimSize) {
    this.workspaceState.setTrim(size);
    this.workspaceState.recalcSpine();
    this.workspaceState.clearPdfPath();
    this.refreshComposite();
    this.saveParams();
  }

  recalculateSpine() {
    this.workspaceState.recalcSpine();
    this.workspaceState.clearPdfPath();
    this.saveParams();
    this.compositeCache.clear();
    this.refreshComposite();
  }

  getPageHeight(): number {
    if (!this.workspace) return 0;
    return this.preview.getPageHeight(this.workspace);
  }

  getPageRatio(): string {
    if (!this.workspace) return "1/1";
    return this.preview.getPageRatio(this.workspace);
  }

  getPreviewPageRatio(index: number): string {
    if (!this.workspace) return "1/1";
    const w = this.preview.getPreviewPageWidth(this.workspace, index);
    const h = this.preview.getPageHeight(this.workspace);
    return `${w}/${h}`;
  }

  getPreviewPageWidth(index: number): number {
    if (!this.workspace) return 0;
    return this.preview.getPreviewPageWidth(this.workspace, index);
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

  /** 素材删除/上传/选择后统一收口 workspace 更新，并清除旧 PDF 标记。 */
  onMaterialChanged(ws: WorkspaceState) {
    if (!ws) return;
    this.workspaceState.setWorkspace(ws);
    this.workspaceState.clearPdfPath();
  }

  private updateWorkspaceParams(
    updater: (ws: WorkspaceState) => WorkspaceState,
  ): void {
    this.workspaceState.batchUpdate((ws) => {
      const next = updater(ws);
      const pageCount = next.page_count ?? 0;
      const paperThickness = next.paper_thickness ?? 0;
      const spineWidth = calcSpineWidth(pageCount, paperThickness);
      const pdfPath = next.pdf_path == null ? next.pdf_path : null;

      if (
        next.spine_width_mm === spineWidth &&
        next.pdf_path === pdfPath
      ) {
        return next;
      }

      return {
        ...next,
        spine_width_mm: spineWidth,
        pdf_path: pdfPath,
      };
    });
    this.compositeCache.clear();
    this.refreshComposite();
    this.saveParams();
  }

  onPageCountChange(value: number) {
    this.updateWorkspaceParams((ws) => ({
      ...ws,
      page_count: value,
    }));
  }

  onPaperThicknessChange(value: number) {
    this.updateWorkspaceParams((ws) => ({
      ...ws,
      paper_thickness: value,
    }));
  }

  onSpineWidthChange(value: number) {
    this.workspaceState.batchUpdate((ws) => ({
      ...ws,
      spine_width_mm: value,
      pdf_path: ws.pdf_path == null ? ws.pdf_path : null,
    }));
    this.compositeCache.clear();
    this.refreshComposite();
    this.saveParams();
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

    if (ws.pdf_path) {
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
      target: "all" as const,
    };

    try {
      await this._runAllWithSse(request);
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
  private _runAllWithSse(request: AiGenerateAllRequest): Promise<void> {
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
   * 预览原始PDF（电子书PDF）
   */
  previewPdf(): void {
    this.router.navigate(["/pdf-reader", "source-print", this.bookId]);
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

  /**
   * ============================================================
   * Gemini AI 配置管理
   * ============================================================
   */

  /** 打开 AI 配置弹窗 */
  openAiConfig(): void {
    this.aiConfigLoading = true;
    this.aiConfigVisible = true;

    this.print.getAiConfig().subscribe({
      next: (result) => {
        this.aiConfigLoading = false;
        this.aiConfigBundle = result;
      },
      error: (err) => {
        this.aiConfigLoading = false;
        console.error('加载 AI 配置失败', err);
        alert('加载配置失败，请检查 print-engine 服务');
      },
    });
  }

  /** 处理 AI 配置保存/测试 */
  onAiConfigSave(event: any): void {
    if (event.action === 'test') {
      // 测试连接（传入完整 runtime 配置，包含 profiles）
      this.print.testAiConfig(event.payload).subscribe({
        next: (result) => {
          event.callback(result);
        },
        error: (err) => {
          event.callback({
            success: false,
            error: err.error?.detail || err.error?.error || err.message || '连接失败',
          });
        },
      });
    } else if (event.action === 'save') {
      // 保存配置（runtime 包含 activeProfileId + profiles[]）
      const bundle = {
        runtime: event.runtime,
        prompts: event.prompts,
      };
      this.print.saveAiConfig(bundle).subscribe({
        next: () => {
          this.aiConfigBundle = bundle;
          event.callback(true);
        },
        error: (err) => {
          console.error('保存 AI 配置失败', err);
          event.callback(false);
        },
      });
    }
  }

  /** 关闭 AI 配置弹窗 */
  closeAiConfig(): void {
    this.aiConfigVisible = false;
  }

  /**
   * ============================================================
   * Gemini 展开图生成与裁切
   * ============================================================
   */

  private buildSpreadPreview(payload: {
    spread_filename: string;
    spread_size?: { width?: number; height?: number };
    crop_lines?: {
      vertical_lines?: number[];
      horizontal_lines?: number[];
      vertical?: number[];
      horizontal?: number[];
    };
    source_cover_filename?: string | null;
    updated_at?: string;
  }): SpreadPreviewItem {
    const verticalLines = payload.crop_lines?.vertical_lines?.length
      ? payload.crop_lines.vertical_lines
      : (payload.crop_lines?.vertical || []);
    const horizontalLines = payload.crop_lines?.horizontal_lines?.length
      ? payload.crop_lines.horizontal_lines
      : (payload.crop_lines?.horizontal || []);

    return {
      imageUrl: this.print.getAssetUrl(this.bookId, 'preview', payload.spread_filename),
      spreadFilename: payload.spread_filename,
      spreadWidth: payload.spread_size?.width || 0,
      spreadHeight: payload.spread_size?.height || 0,
      cropLines: {
        vertical_lines: verticalLines,
        horizontal_lines: horizontalLines,
      },
      sourceCoverUrl: payload.source_cover_filename
        ? this.material.getAssetUrl(this.bookId, 'cover', payload.source_cover_filename)
        : '',
      updatedAt: payload.updated_at
        ? new Intl.DateTimeFormat('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          }).format(new Date(payload.updated_at))
        : '',
    };
  }

  private syncSpreadHistoryFromWorkspace(ws: WorkspaceState | null): void {
    const history = [ ...((ws?.ai_crop_history ?? []) as AiCropHistoryItem[]) ];
    const draft = ws?.ai_crop_draft;

    if (draft?.spread_filename && !history.some((item) => item?.spread_filename === draft.spread_filename)) {
      history.unshift(draft);
    }

    this.spreadHistory = history
      .filter((item): item is AiCropHistoryItem => !!item?.spread_filename)
      .map((item) => this.buildSpreadPreview(item));
  }

  private syncSpreadPreviewWithHistory(): void {
    if (!this.spreadPreview?.spreadFilename) {
      return;
    }

    const refreshed = this.spreadHistory.find(
      item => item.spreadFilename === this.spreadPreview?.spreadFilename
    );

    if (refreshed) {
      this.spreadPreview = { ...refreshed };
    }
  }

  private openSpreadPreviewByFilename(spreadFilename: string): boolean {
    const target = this.spreadHistory.find((item) => item.spreadFilename === spreadFilename);
    if (!target) {
      return false;
    }
    this.spreadPreview = { ...target };
    this.aiCropVisible = true;
    return true;
  }

  private tryOpenDraftPreview(ws: WorkspaceState): boolean {
    const draft = ws.ai_crop_draft;
    if (!draft?.spread_filename) {
      return false;
    }

    const opened = this.openSpreadPreviewByFilename(draft.spread_filename);
    if (!opened) {
      this.spreadPreview = this.buildSpreadPreview(draft);
      this.aiCropVisible = true;
    }
    this.addLog('📝 已打开缓存的展开图草稿', 100, true);
    return true;
  }

  /**
   * 启动 Gemini 展开图生成（新流程）
   * 替代旧的 onAiGenerate() SSE 流程
   */
  openAiCropDialog(): void {
    const ws = this.workspace;
    if (!ws) {
      return;
    }

    this.syncSpreadHistoryFromWorkspace(ws);

    if (this.tryOpenDraftPreview(ws)) {
      return;
    }

    if (this.spreadPreview?.spreadFilename) {
      const refreshed = this.spreadHistory.find(
        item => item.spreadFilename === this.spreadPreview?.spreadFilename
      );
      if (refreshed) {
        this.spreadPreview = { ...refreshed };
        this.aiCropVisible = true;
        return;
      }
    }

    const latestHistory = this.spreadHistory[0];
    this.spreadPreview = latestHistory ? { ...latestHistory } : null;
    this.aiCropVisible = true;
  }

  onDialogGenerate(): void {
    this.onAiGenerateSpread();
  }

  async onAiGenerateSpread(): Promise<void> {
    if (!this.canAiGenerate || this.aiGenerating) {
      return;
    }

    const ws = this.workspace;
    if (!ws) {
      alert('workspace 未初始化');
      return;
    }

    this.aiGenerating = true;
    this.aiLastResult = null;
    this.aiErrorMsg = '';
    this.aiProgress = 0;
    this.aiProgressText = '生成展开图中...';
    this.aiPhaseText = '准备中';
    this.aiLogMessages = [];
    this.addLog('开始生成新的 Gemini 展开图...', 0, true);

    const request = {
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
      spine_width_mm: ws.spine_width_mm,
      template_id: this.aiConfigBundle?.prompts?.activeTemplateId || null,
    };

    this.print.generateSpread(this.bookId, request).subscribe({
      next: (result) => {
        this.aiGenerating = false;
        this.aiProgress = 100;
        this.aiPhaseText = '✅ 展开图生成完成';
        this.addLog('✅ 展开图生成成功，打开裁切窗口', 100, true);

        if (result.workspace) {
          this.workspaceState.setWorkspace(result.workspace);
        }

        const nextSpreadFilename = result.spread_filename || result.workspace?.ai_crop_draft?.spread_filename;
        if (nextSpreadFilename) {
          const opened = this.openSpreadPreviewByFilename(nextSpreadFilename);
          if (!opened) {
            const historyItem = (result.workspace?.ai_crop_history || []).find(
              (item: AiCropHistoryItem) => item.spread_filename === nextSpreadFilename,
            );
            this.spreadPreview = this.buildSpreadPreview(
              historyItem || result.workspace?.ai_crop_draft || result,
            );
            this.aiCropVisible = true;
          }
        } else {
          this.spreadPreview = this.buildSpreadPreview(result);
          this.aiCropVisible = true;
        }
      },
      error: (err) => {
        this.aiGenerating = false;
        this.aiLastResult = 'error';
        this.aiErrorMsg = err.name === 'TimeoutError'
          ? '生成超时，请稍后重试'
          : (err.error?.error || '生成失败');
        this.addLog(`❌ 生成失败: ${this.aiErrorMsg}`, 0, true);
        console.error('Gemini 展开图生成失败', err);
      },
    });
  }

  /**
   * 保存裁切结果
   *
   * 生命周期：
   * 1. 保存裁切线到后端，生成 front_output/spine/back 素材
   * 2. 后端更新 ai_crop_history，清空 ai_crop_draft
   * 3. 前端从返回的 workspace 重建 spreadHistory
   * 4. 从新 history 中找到刚保存的项，更新 spreadPreview
   * 5. 关闭弹窗
   */
  onCropSave(event: any): void {
    const ws = this.workspace;
    if (!ws || !this.spreadPreview) {
      alert('数据异常，无法保存');
      return;
    }

    this.cropSaving = true;
    const savedSpreadFilename = this.spreadPreview.spreadFilename;
    const request = {
      spread_filename: savedSpreadFilename,
      vertical_lines: event.vertical_lines,
      horizontal_lines: event.horizontal_lines,
    };

    this.print.saveCroppedMaterials(this.bookId, request).subscribe({
      next: (result) => {
        this.cropSaving = false;
        const nextWorkspace = result?.workspace ?? result;
        this.workspaceState.setWorkspace(nextWorkspace);

        // 从返回的 workspace 重建 history，找到刚保存的项
        const nextHistory = [...((nextWorkspace?.ai_crop_history ?? []) as AiCropHistoryItem[])];
        const savedItem = nextHistory.find(item => item?.spread_filename === savedSpreadFilename);

        if (savedItem) {
          this.spreadPreview = this.buildSpreadPreview(savedItem);
        }

        this.aiCropVisible = false;
        this.aiLastResult = 'success';
        this.addLog('✅ 裁切保存成功，素材已回填', 100, true);
      },
      error: (err) => {
        this.cropSaving = false;
        alert('保存失败：' + (err.error?.error || '未知错误'));
      },
    });
  }

  /** 关闭裁切弹窗，保留当前展开图状态 */
  closeCrop(): void {
    this.aiCropVisible = false;
  }

  onSpreadHistorySelect(spreadFilename: string): void {
    this.openSpreadPreviewByFilename(spreadFilename);
  }

  onSpreadHistoryDelete(spreadFilename: string): void {
    const deletingCurrentPreview = this.spreadPreview?.spreadFilename === spreadFilename;

    this.print.deleteAiCropHistory(this.bookId, spreadFilename).subscribe({
      next: (workspace) => {
        this.workspaceState.setWorkspace(workspace);

        if (!deletingCurrentPreview) {
          this.addLog('🗑️ 已删除历史展开图', 100, true);
          return;
        }

        const nextHistory = [...((workspace?.ai_crop_history ?? []) as AiCropHistoryItem[])];
        const nextItem = nextHistory[0] ?? null;

        if (nextItem) {
          this.spreadPreview = this.buildSpreadPreview(nextItem);
        } else {
          this.aiCropVisible = false;
          this.spreadPreview = null;
        }

        this.addLog('🗑️ 已删除历史展开图', 100, true);
      },
      error: (err) => {
        alert('删除历史展开图失败：' + (err.error?.error || '未知错误'));
      },
    });
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
        console.log('[PDF Info] 后端返回:', result);

        if (result.success && result.data) {
          const data = result.data;
          const matchedSize = this.matchStandardSize(data.width_mm, data.height_mm);

          console.log('[PDF Info] 原始尺寸:', data.width_mm, 'x', data.height_mm, 'mm');
          console.log('[PDF Info] 匹配结果:', matchedSize);

          this.pdfSizeInfo = {
            width: Math.round(data.width_mm),
            height: Math.round(data.height_mm),
            orientation: this.translateOrientation(data.orientation),
            matchedSize: matchedSize,
            loading: false,
            error: ''
          };
        } else {
          console.warn('[PDF Info] 获取失败:', result.error);
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
        console.error('[PDF Info] 请求失败:', err);
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

        // 更新状态（只在字段存在时更新，避免重置已有计数）
        this.resizeProgress = data.progress ?? this.resizeProgress;
        this.resizeStage = data.stage ?? this.resizeStage;

        // 只在后端明确返回计数字段时才更新（避免 undefined 被当作 0）
        if (data.double_pages_count !== undefined) {
          this.resizeDoubleCount = data.double_pages_count;
        }
        if (data.single_pages_count !== undefined) {
          this.resizeSingleCount = data.single_pages_count;
        }
        if (data.error_pages_count !== undefined) {
          this.resizeErrorCount = data.error_pages_count;
        }

        // 兼容旧后端：如果未返回计数字段，尝试从 stage 文本中解析“双页:X 单页:Y”
        // 示例: "[23/120] ✅ 完成 | 双页:4 单页:19"
        if ((this.resizeDoubleCount === 0 && this.resizeSingleCount === 0) && this.resizeStage) {
          const stageText = String(this.resizeStage);
          const doubleMatch = stageText.match(/双页[:：]\s*(\d+)/);
          const singleMatch = stageText.match(/单页[:：]\s*(\d+)/);
          const errorMatch = stageText.match(/错误[:：]\s*(\d+)/);

          if (doubleMatch) {
            this.resizeDoubleCount = Number(doubleMatch[1]) || 0;
          }
          if (singleMatch) {
            this.resizeSingleCount = Number(singleMatch[1]) || 0;
          }
          if (errorMatch) {
            this.resizeErrorCount = Number(errorMatch[1]) || 0;
          }
        }

        // ============================================
        // 日志记录策略：只记录关键节点，避免刷屏
        // ============================================
        const isKeyNode =
          // 关键进度节点
          data.progress === 10 ||
          data.progress === 50 ||
          data.progress === 88 ||
          data.progress === 95 ||
          // 特殊子阶段
          data.sub_stage === 'done' ||
          data.sub_stage === 'error' ||
          data.sub_stage === 'splitting' ||
          data.sub_stage === 'formatting_left' ||
          data.sub_stage === 'formatting_right';

        if (isKeyNode) {
          this.addResizeLog(`⏳ ${data.stage}`);
        }

        // ============================================
        // 任务完成处理
        // ============================================
        if (data.status === 'done') {
          es.close();
          this.resizing = false;
          this.resizeProgress = 100;

          if (data.skipped) {
            // 已是目标尺寸，跳过处理
            this.addResizeLog('✓ 已是目标尺寸，跳过处理');
            this.saveResizeLogs(); // 保存日志
            alert(data.message || 'PDF已经是目标尺寸，无需格式化');
          } else {
            // 格式化成功
            this.addResizeLog('✅ 格式化完成');
            if (data.new_size) {
              this.addResizeLog(`📐 新尺寸: ${data.new_size.width_mm}×${data.new_size.height_mm}mm`);
            }
            // 输出统计摘要
            const errStr = this.resizeErrorCount > 0 ? ` | ❌错误 ${this.resizeErrorCount}` : '';
            this.addResizeLog(`📊 统计: ✂️双页 ${this.resizeDoubleCount} | 📄单页 ${this.resizeSingleCount}${errStr}`);

            // 保存日志到 localStorage
            this.saveResizeLogs();

            // 询问是否预览
            const shouldPreview = confirm('PDF格式化完成！是否立即预览？');
            if (shouldPreview) {
              this.previewPdf();
            }
          }

          // 延迟刷新PDF尺寸信息，确保数据一致性
          setTimeout(() => this.loadPdfInfo(), 500);
        }

        // ============================================
        // 任务错误处理
        // ============================================
        if (data.status === 'error') {
          es.close();
          this.resizing = false;
          const errorMsg = data.error || '未知错误';
          // 简化错误信息，只保留关键部分
          const shortError = errorMsg.includes('第')
            ? errorMsg.split('详细信息')[0].trim()
            : errorMsg;
          this.addResizeLog(`❌ 处理失败: ${shortError}`);
          this.handleResizeError(errorMsg);
        }

        this.cdr.detectChanges();
      } catch (e) {
        // JSON 解析失败，记录错误但不中断连接
        console.error('SSE数据解析失败:', e);
        this.addResizeLog('⚠️ 数据解析异常');
        this.cdr.detectChanges();
      }
    };

    // 连接错误处理
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        es.close();
        // 只有在任务未完成时才报告连接中断
        if (this.resizing) {
          this.addResizeLog('❌ SSE连接中断');
          this.handleResizeError('与服务器的连接已断开');
        }
      }
    };
  }

  /**
   * 处理格式化错误
   * - 重置所有状态
   * - 提示用户错误信息
   */
  private handleResizeError(message: string): void {
    this.resizing = false;
    this.resizeProgress = 0;
    this.resizeStage = '';
    this.resizeDoubleCount = 0;
    this.resizeSingleCount = 0;
    this.resizeErrorCount = 0;
    alert('格式化失败：' + message);
    this.cdr.detectChanges();
  }

  /**
   * 添加格式化日志
   * - 自动截取时间戳
   * - 限制最多保留 5 条，避免过长
   */
  private addResizeLog(message: string): void {
    const timestamp = new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
    this.resizeLogs.push(timestamp + ' ' + message);
    this.cdr.detectChanges();
  }

  /**
   * 保存格式化日志到 localStorage
   * - 完成时调用，方便返回后查看
   */
  private saveResizeLogs(): void {
    try {
      const key = 'resize_logs_' + this.bookId;
      const data = {
        logs: this.resizeLogs,
        doubleCount: this.resizeDoubleCount,
        singleCount: this.resizeSingleCount,
        errorCount: this.resizeErrorCount,
        timestamp: Date.now(),
      };
      localStorage.setItem(key, JSON.stringify(data));
    } catch (e) {
      console.warn('保存日志失败:', e);
    }
  }

  /**
   * 恢复格式化日志从 localStorage
   * - 页面加载时调用
   * - 只恢复最近 5 分钟内的日志
   */
  private restoreResizeLogs(): void {
    try {
      const key = 'resize_logs_' + this.bookId;
      const stored = localStorage.getItem(key);
      if (!stored) return;

      const data = JSON.parse(stored);
      const age = Date.now() - (data.timestamp || 0);

      if (age < 5 * 60 * 1000) {
        this.resizeLogs = data.logs || [];
        this.resizeDoubleCount = data.doubleCount || 0;
        this.resizeSingleCount = data.singleCount || 0;
        this.resizeErrorCount = data.errorCount || 0;
        this.cdr.detectChanges();
      } else {
        // 过期日志清除
        localStorage.removeItem(key);
      }
    } catch (e) {
      console.warn('恢复日志失败:', e);
    }
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
      const portraitMatch = Math.abs(width - w) <= TOLERANCE && Math.abs(height - h) <= TOLERANCE;
      const landscapeMatch = Math.abs(width - h) <= TOLERANCE && Math.abs(height - w) <= TOLERANCE;

      if (portraitMatch || landscapeMatch) {
        return name;
      }
    }

    return null;
  }
}
