/*
============================================================
Booklore Print Workspace Material Service
版本：V1.4

变更：
- 改为纯请求层，不再直接写 WorkspaceStateService
- 所有方法返回 Observable<WorkspaceState>
- 调用方需要订阅返回值并调用 workspaceState.setWorkspace()

重要：
本服务只负责发起 HTTP 请求并返回结果，不负责状态更新。
调用方必须订阅返回的 Observable<WorkspaceState> 并手动调用
workspaceState.setWorkspace(ws) 来更新全局状态。

示例：
  this.material.uploadMaterial(bookId, type, file).subscribe({
    next: (ws) => this.workspaceState.setWorkspace(ws),
    error: (err) => console.error(err)
  });

如果忘记订阅或忘记 setWorkspace()，前端状态不会更新，
但后端已经成功保存，会导致前后端状态不一致。
============================================================
*/

import { Injectable } from "@angular/core";
import { Observable } from "rxjs";
import { PrintService, WorkspaceState } from "./print.service";

export type MaterialType = "cover" | "front_output" | "spine" | "back";
export type UploadMaterialType = "cover" | "spine" | "back";
export type AiGenerateMaterialType = "spine" | "back";

@Injectable({
  providedIn: "root",
})
export class MaterialService {
  constructor(
    private print: PrintService,
  ) {}

  getAssetUrl(
    bookId: number,
    type: MaterialType,
    filename: string | null,
  ): string {
    if (!filename) return "";
    return this.print.getAssetUrl(bookId, type, filename);
  }

  getEffectiveFrontSelection(bookId: number, ws: WorkspaceState | null): {
    selected: string | null;
    url: string;
    type: MaterialType | null;
    usingFrontOutput: boolean;
  } {
    if (!ws) {
      return {
        selected: null,
        url: "",
        type: null,
        usingFrontOutput: false,
      };
    }

    const frontSelected = ws.front_output?.selected ?? null;
    if (frontSelected) {
      return {
        selected: frontSelected,
        url: this.getAssetUrl(bookId, "front_output", frontSelected),
        type: "front_output",
        usingFrontOutput: true,
      };
    }

    const coverSelected = ws.cover?.selected ?? null;
    return {
      selected: coverSelected,
      url: this.getAssetUrl(bookId, "cover", coverSelected),
      type: coverSelected ? "cover" : null,
      usingFrontOutput: false,
    };
  }

  uploadMaterial(
    bookId: number,
    type: UploadMaterialType,
    file: File,
  ): Observable<WorkspaceState> {
    return this.print.uploadMaterial(bookId, type, file);
  }

  deleteMaterial(
    bookId: number,
    type: MaterialType,
    filename: string,
  ): Observable<WorkspaceState> {
    return this.print.deleteMaterial(bookId, type, filename);
  }

  selectMaterial(
    bookId: number,
    type: MaterialType,
    filename: string,
  ): Observable<WorkspaceState> {
    return this.print.selectMaterial(bookId, type, filename);
  }

  aiGenerateMaterial(
    bookId: number,
    type: AiGenerateMaterialType,
    trimSize: string,
    pageCount: number,
    paperThickness: number,
  ): Observable<WorkspaceState> {
    return this.print.aiGenerate(bookId, type, {
      trimSize,
      pageCount,
      paperThickness,
    });
  }
}
