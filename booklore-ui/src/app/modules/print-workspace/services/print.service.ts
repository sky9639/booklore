// print.service.ts

import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable } from "rxjs";
import { environment } from "../../../../environments/environment";
import { TrimSize } from "../models/workspace.model";

// workspace.json 对应的 TS 结构
export interface WorkspaceCategory {
  selected: string | null;
  history: string[];
}

export interface WorkspaceState {
  book_name?: string;
  trim_size?: TrimSize;
  page_count?: number;
  paper_thickness?: number;
  spine_width_mm?: number;
  cover?: WorkspaceCategory;
  spine?: WorkspaceCategory;
  back?: WorkspaceCategory;
  preview_path?: string;
  pdf_path?: string;
  updated_at?: string;
}

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
}
