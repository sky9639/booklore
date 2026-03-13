/*
============================================================
Booklore Print Workspace Material Service
版本：V1.3

变更：
- aiGenerateMaterial request 字段名与 PrintRequest 对齐（驼峰）
- workspace-state 统一使用 WorkspaceState 类型
============================================================
*/

import { Injectable } from "@angular/core";
import { Observable } from "rxjs";
import { PrintService, WorkspaceState } from "./print.service";
import { WorkspaceStateService } from "./workspace-state.service";

export type MaterialType = "cover" | "spine" | "back";

@Injectable({
  providedIn: "root",
})
export class MaterialService {
  constructor(
    private print: PrintService,
    private state: WorkspaceStateService,
  ) {}

  getAssetUrl(
    bookId: number,
    type: MaterialType,
    filename: string | null,
  ): string {
    if (!filename) return "";
    return this.print.getAssetUrl(bookId, type, filename);
  }

  getHistory(type: MaterialType): string[] {
    const ws = this.state.workspace;
    if (!ws) return [];
    return ws[type]?.history ?? [];
  }

  uploadMaterial(
    bookId: number,
    type: MaterialType,
    file: File,
  ): Observable<WorkspaceState> {
    return new Observable((observer) => {
      this.print.uploadMaterial(bookId, type, file).subscribe({
        next: (updatedWs: WorkspaceState) => {
          if (updatedWs) this.state.setWorkspace(updatedWs);
          observer.next(updatedWs);
          observer.complete();
        },
        error: (err: unknown) => observer.error(err),
      });
    });
  }

  deleteMaterial(
    bookId: number,
    type: MaterialType,
    filename: string,
  ): Observable<WorkspaceState> {
    return this.print.deleteMaterial(bookId, type, filename);
  }

  selectMaterial(bookId: number, type: MaterialType, filename: string): void {
    this.print
      .selectMaterial(bookId, type, filename)
      .subscribe((ws: WorkspaceState) => {
        this.state.setWorkspace(ws);
      });
  }

  aiGenerateMaterial(
    bookId: number,
    type: MaterialType,
  ): Observable<WorkspaceState> {
    const ws = this.state.workspace;
    if (!ws) return new Observable((o) => o.error("Workspace not initialized"));

    if (type === "cover")
      return new Observable((o) =>
        o.error("cover does not support AI generation"),
      );

    return new Observable((observer) => {
      this.print
        .aiGenerate(bookId, type, {
          trimSize: ws.trim_size,
          pageCount: ws.page_count,
          paperThickness: ws.paper_thickness,
        })
        .subscribe({
          next: (updatedWs: WorkspaceState) => {
            this.state.setWorkspace(updatedWs);
            observer.next(updatedWs);
            observer.complete();
          },
          error: (err: unknown) => observer.error(err),
        });
    });
  }
}
