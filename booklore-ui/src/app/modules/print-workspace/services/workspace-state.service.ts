/*
============================================================
Booklore Print Workspace State Service
版本：V1.4
变更：
- 统一使用 WorkspaceState 类型（替代 PrintWorkspace）
- 消除 WorkspaceState / PrintWorkspace 类型不兼容问题
============================================================
*/
import { Injectable } from "@angular/core";
import { BehaviorSubject } from "rxjs";
import { TrimSize } from "../models/workspace.model";
import { WorkspaceState } from "./print.service";
import { calcSpineWidth } from "../utils/dimension.util";

@Injectable({
  providedIn: "root",
})
export class WorkspaceStateService {
  private _workspace$ = new BehaviorSubject<WorkspaceState | null>(null);

  /** 组件订阅此流，素材上传/删除/选择后自动收到新 workspace */
  readonly workspace$ = this._workspace$.asObservable();

  /** 同步读取当前 workspace */
  get workspace(): WorkspaceState | null {
    return this._workspace$.getValue();
  }

  setWorkspace(ws: WorkspaceState): void {
    this._workspace$.next(ws);
  }

  setTrim(size: TrimSize): void {
    const ws = this.workspace;
    if (!ws) return;
    ws.trim_size = size;
  }

  setPageCount(count: number): void {
    const ws = this.workspace;
    if (!ws) return;
    ws.page_count = count;
  }

  setPaperThickness(v: number): void {
    const ws = this.workspace;
    if (!ws) return;
    ws.paper_thickness = v;
  }

  recalcSpine(): void {
    const ws = this.workspace;
    if (!ws) return;
    const pages = ws.page_count ?? 0;
    const thickness = ws.paper_thickness ?? 0;
    ws.spine_width_mm = calcSpineWidth(pages, thickness);
  }
}
