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

import { Component, OnInit, OnDestroy, HostListener } from "@angular/core";
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

  private compositeCache = new Map<string, string>();
  private wsSub?: Subscription;
  compositeUrl = "";
  lightboxUrl = "";

  /** [V1.9] PDF 生成中状态 */
  pdfGenerating = false;

  /** [V1.9] PDF 生成错误信息 */
  pdfError = "";

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
    });

    this.initWorkspace();
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
  // ★ 统一 AI 生成入口（spine + back 合并任务，一次 SSE 全程）
  // ─────────────────────────────────────────────────────────────
  aiProgress = 0;
  aiPhaseText = "";

  async onAiGenerate(): Promise<void> {
    if (!this.canAiGenerate || this.aiGenerating) return;

    this.aiGenerating = true;
    this.aiLastResult = null;
    this.aiErrorMsg = "";
    this.aiProgress = 0;
    this.aiProgressText = "AI 生成中...";
    this.aiPhaseText = "准备中";

    const ws = this.workspace;
    if (!ws) {
      this.aiErrorMsg = "workspace 未初始化";
      this.aiLastResult = "error";
      this.aiGenerating = false;
      return;
    }

    const request = {
      trimSize: ws.trim_size,
      pageCount: ws.page_count,
      paperThickness: ws.paper_thickness,
      target: "all", // 后端一次完成 spine + back
    };

    try {
      await this._runAllWithSse(request as any);
      this.aiLastResult = "success";
      this.aiProgress = 100;
    } catch (error: unknown) {
      this.aiLastResult = "error";
      const e = error as { message?: string };
      this.aiErrorMsg = e?.message ?? "网络异常，请检查服务器连接";
      console.error("[AI Generate] 失败:", error);
    } finally {
      this.aiGenerating = false;
      this.aiProgressText = "AI 生成书脊 & 封底";
      this.aiPhaseText = "";
    }
  }

  private _runAllWithSse(request: any): Promise<void> {
    return new Promise((resolve, reject) => {
      // Step 1: POST start → 拿 task_id
      this.print.aiGenerateStart(this.bookId, "all", request).subscribe({
        next: (res: any) => {
          const taskId = res.task_id;
          // 直连 Python print-engine SSE，绕过 Java/nginx 代理避免超时断线
          // print-engine 暴露在宿主机 5800 端口
          const pythonBase = `${window.location.protocol}//${window.location.hostname}:5800`;
          const url = `${pythonBase}/workspace/ai-generate/progress/${taskId}`;
          const es = new EventSource(url);

          es.onmessage = (event: MessageEvent) => {
            try {
              const data = JSON.parse(event.data);

              // 更新进度条
              if (data.pct !== undefined) {
                this.aiProgress = data.pct;
              }

              // 更新阶段文字
              if (data.phase === "spine") {
                this.aiPhaseText = "生成书脊中...";
              } else if (data.phase === "back") {
                this.aiPhaseText = "生成封底中...";
              }

              if (data.status === "done") {
                es.close();
                if (data.ws) {
                  this.workspaceState.setWorkspace(data.ws);
                  // 刷新合成预览
                  this.compositeCache.clear();
                  this.refreshComposite();
                }
                this.aiProgress = 100;
                resolve();
              } else if (data.status === "error") {
                es.close();
                reject(new Error(data.error ?? "AI 生成失败"));
              }
            } catch (e) {
              es.close();
              reject(e);
            }
          };

          es.onerror = (ev) => {
            // 心跳行（": heartbeat"）会触发 onerror in some browsers，忽略
            // 真正的连接断开 readyState 会变成 CLOSED(2)
            if (es.readyState === EventSource.CLOSED) {
              es.close();
              reject(new Error("SSE 连接断开"));
            }
            // readyState === CONNECTING(0) 表示自动重连，不报错
          };
        },
        error: (err: any) => {
          const msg =
            err?.error?.error ??
            err?.error?.message ??
            err?.message ??
            "AI 生成请求失败";
          reject(new Error(msg));
        },
      });
    });
  }
  /** 跳转到官方 PDF 阅读器（print 模式） */
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
}
