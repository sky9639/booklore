/*
============================================================
Booklore Print Workspace State Service
版本：V1.5

变更：
- 统一使用 WorkspaceState 类型（替代 PrintWorkspace）
- 消除 WorkspaceState / PrintWorkspace 类型不兼容问题
- 修正状态发布机制：所有修改 workspace 的方法都通过 next() 发布新状态
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

  private updateWorkspace(updater: (workspace: WorkspaceState) => WorkspaceState): void {
    const ws = this.workspace;
    if (!ws) return;
    const next = updater(ws);
    if (next === ws) return;
    this._workspace$.next(next);
  }

  /** 组件订阅此流，素材上传/删除/选择后自动收到新 workspace */
  readonly workspace$ = this._workspace$.asObservable();

  /** 同步读取当前 workspace */
  get workspace(): WorkspaceState | null {
    return this._workspace$.getValue();
  }

  /**
   * 设置 workspace 并发布状态
   *
   * 这是前端唯一的 workspace 更新入口。
   * 所有会修改 workspace 的操作都应通过此方法发布新状态，
   * 以确保订阅者能感知到变更。
   */
  setWorkspace(ws: WorkspaceState): void {
    this._workspace$.next(ws);
  }

  /**
   * 修改成书尺寸并发布状态
   *
   * 注意：修改后会立即发布新状态，触发订阅者刷新
   */
  setTrim(size: TrimSize): void {
    this.updateWorkspace((ws) => ({
      ...ws,
      trim_size: size,
    }));
  }

  /**
   * 修改页数并发布状态
   */
  setPageCount(count: number): void {
    this.updateWorkspace((ws) => ({
      ...ws,
      page_count: count,
    }));
  }

  /**
   * 修改纸张厚度并发布状态
   */
  setPaperThickness(v: number): void {
    this.updateWorkspace((ws) => ({
      ...ws,
      paper_thickness: v,
    }));
  }

  /**
   * 手动修改书脊宽度并发布状态
   */
  setSpineWidth(width: number): void {
    this.updateWorkspace((ws) => ({
      ...ws,
      spine_width_mm: width,
    }));
  }

  /**
   * 清除已生成 PDF 标记并发布状态。
   * 参数变化、素材变化后都应调用此方法，避免复用过期 PDF。
   */
  clearPdfPath(): void {
    this.updateWorkspace((ws) => {
      if (ws.pdf_path == null) return ws;
      return {
        ...ws,
        pdf_path: null,
      };
    });
  }

  /**
   * 重新计算书脊宽度并发布状态
   *
   * 公式：spine_width_mm = page_count × paper_thickness
   */
  recalcSpine(): void {
    this.updateWorkspace((ws) => {
      const pages = ws.page_count ?? 0;
      const thickness = ws.paper_thickness ?? 0;
      const spineWidth = calcSpineWidth(pages, thickness);
      if (ws.spine_width_mm === spineWidth) return ws;
      return {
        ...ws,
        spine_width_mm: spineWidth,
      };
    });
  }

  /**
   * 批量更新 workspace 字段，只发布一次状态
   *
   * 用于避免连续多次 set 操作触发多次订阅刷新
   */
  batchUpdate(updater: (ws: WorkspaceState) => WorkspaceState): void {
    this.updateWorkspace(updater);
  }
}
