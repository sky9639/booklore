import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable, timeout } from "rxjs";
import { environment } from "../../../../environments/environment";
import type {
  TrimSize,
  PrintWorkspace,
  AiCropDraft,
  AiCropHistoryItem
} from "../models/workspace.model";

// 为保持向后兼容，WorkspaceState 作为 PrintWorkspace 的别名
export type WorkspaceState = PrintWorkspace;
export type WorkspaceCategory = PrintWorkspace['cover'];

export type { AiCropDraft, AiCropHistoryItem };

export interface PrintRequest {
  trimSize?: string;
  pageCount?: number;
  paperThickness?: number;
  spineMode?: string;
  backMode?: string;
}

@Injectable({ providedIn: "root" })
export class PrintService {
  readonly baseUrl = environment.API_CONFIG.BASE_URL + "/api/v1";

  constructor(private http: HttpClient) {}

  /** 初始化工作台 */
  initWorkspace(bookId: number | string): Observable<WorkspaceState> {
    return this.http.post<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/workspace/init`,
      {},
    );
  }

  /** 手动上传素材 */
  uploadMaterial(
    bookId: number | string,
    category: "cover" | "spine" | "back",
    file: File,
  ): Observable<WorkspaceState> {
    const form = new FormData();
    form.append("file", file);
    return this.http.post<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/workspace/upload/${category}`,
      form,
    );
  }

  /**
   * AI 生成书脊或封底
   *
   * Java 侧（PrintController.aiGenerateMaterial）：
   *   → 调 print-engine /ai-generate 拿 PNG bytes
   *   → 命名 ai_{target}_{timestamp}.png 存入 .print/{target}/
   *   → 更新 workspace.json
   *   → 返回完整 workspace JSON
   *
   * 前端拿到 workspace 后用 getAssetUrl() 拼图片 URL 回填缩略图
   */
  aiGenerate(
    bookId: number | string,
    target: "spine" | "back",
    request: PrintRequest,
  ): Observable<WorkspaceState> {
    return this.http.post<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/workspace/ai-generate`,
      request,
      { params: { target } },
    );
  }

  /** 启动 AI 生成任务，立即返回 {task_id} */
  aiGenerateStart(
    bookId: number | string,
    target: "all" | "spine" | "back",
    request: any,
  ): Observable<{ task_id: string }> {
    return this.http.post<{ task_id: string }>(
      `${this.baseUrl}/print/${bookId}/workspace/ai-generate/start`,
      { ...request, target },
    );
  }

  /** 切换选中素材 */
  selectMaterial(
    bookId: number | string,
    category: string,
    filename: string,
  ): Observable<WorkspaceState> {
    return this.http.post<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/select`,
      {},
      { params: { category, filename } },
    );
  }

  /** 删除素材 */
  deleteMaterial(
    bookId: number | string,
    category: string,
    filename: string,
  ): Observable<WorkspaceState> {
    return this.http.delete<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/material`,
      { params: { category, filename } },
    );
  }

  /** 生成拼版预览 */
  preview(bookId: number | string, request: PrintRequest): Observable<any> {
    return this.http.post<any>(
      `${this.baseUrl}/print/${bookId}/preview`,
      request,
    );
  }

  /** 生成印刷 PDF */
  generatePdf(bookId: number | string, request: PrintRequest): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/print/${bookId}/pdf`, request);
  }

  /**
   * 拼接素材图片访问 URL
   * GET /api/v1/print/{bookId}/asset/{category}/{filename}
   */
  getAssetUrl(
    bookId: number | string,
    category: string,
    filename: string,
  ): string {
    return `${this.baseUrl}/print/${bookId}/asset/${category}/${filename}`;
  }

  /** 获取PDF信息（尺寸、页数等） */
  getPdfInfo(bookId: number | string): Observable<any> {
    return this.http.post<any>(
      `${this.baseUrl}/print/${bookId}/pdf/info`,
      {}
    );
  }

  /** 启动PDF格式化任务 */
  resizePdf(bookId: number | string, targetSize: string): Observable<{ task_id: string }> {
    return this.http.post<{ task_id: string }>(
      `${this.baseUrl}/print/${bookId}/pdf/resize/start`,
      { target_size: targetSize }
    );
  }

  /**
   * AI 配置相关接口（直连 print-engine 5800 端口，避免 Java 代理）
   * 原因：AI 配置是全局的，不依赖 bookId；且前端已在 SSE 中使用直连模式
   */
  private getPythonBase(): string {
    return `${window.location.protocol}//${window.location.hostname}:5800`;
  }

  /** 获取 AI 配置（联通参数 + 提示词模板） */
  getAiConfig(): Observable<any> {
    const url = `${this.getPythonBase()}/workspace/ai-config`;
    return this.http.get<any>(url);
  }

  /** 保存 AI 配置 */
  saveAiConfig(config: any): Observable<any> {
    const url = `${this.getPythonBase()}/workspace/ai-config`;
    return this.http.post<any>(url, config);
  }

  /** 测试 AI 连接 */
  testAiConfig(runtimeConfig: any): Observable<any> {
    const url = `${this.getPythonBase()}/workspace/ai-config/test`;
    return this.http.post<any>(url, runtimeConfig);
  }

  /** 生成 Gemini 展开图（返回临时预览图和初始裁切线） */
  generateSpread(bookId: number | string, request: any): Observable<any> {
    return this.http
      .post<any>(`${this.baseUrl}/print/${bookId}/workspace/ai-generate/spread`, request)
      .pipe(timeout(300000));
  }

  /** 保存裁切后的书脊和封底 */
  saveCroppedMaterials(bookId: number | string, request: any): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/print/${bookId}/workspace/ai-generate/crop`, request);
  }

  /** 丢弃当前 AI 裁切草稿 */
  discardAiCropDraft(bookId: number | string): Observable<WorkspaceState> {
    return this.http.post<WorkspaceState>(
      `${this.baseUrl}/print/${bookId}/workspace/ai-generate/discard`,
      {},
    );
  }

  /** 删除历史展开图 */
  deleteAiCropHistory(bookId: number | string, spreadFilename: string): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/print/${bookId}/workspace/ai-generate/history/delete`, {
      spread_filename: spreadFilename,
    });
  }
}
