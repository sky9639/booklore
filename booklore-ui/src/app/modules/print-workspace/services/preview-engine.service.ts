/*
============================================================

Booklore Print Workspace Preview Engine
版本：V1.2R-fix01

功能说明：

该模块负责 Print Workspace 的拼版预览计算逻辑。

核心职责：

1 计算单页真实尺寸
2 计算拼版页面宽度
3 生成预览页面比例

设计原则：

• 不依赖 UI
• 不依赖 Angular Component
• 只依赖 Workspace 数据结构
• 所有计算单位为 mm

该模块属于：

Print Workspace Layout Engine

============================================================
*/

import { Injectable } from "@angular/core";
import { PrintWorkspace } from "../models/workspace.model";
import { getTrimWidth, getTrimHeight } from "../utils/dimension.util";

@Injectable({
  providedIn: "root",
})
export class PreviewEngineService {
  /**
   * 获取单页宽度
   *
   * 功能作用：
   * 根据 trim_size 返回书籍页面宽度（mm）
   *
   * 为什么需要：
   * 拼版预览需要根据书籍尺寸计算页面比例
   *
   * 删除后的影响：
   * preview ratio 与拼版宽度计算都会失效
   */
  getPageWidth(ws: PrintWorkspace): number {
    return getTrimWidth(ws.trim_size);
  }

  /**
   * 获取单页高度
   *
   * 功能作用：
   * 根据 trim_size 返回书籍页面高度（mm）
   *
   * 为什么需要：
   * preview 页面需要计算宽高比
   *
   * 删除后的影响：
   * preview ratio 无法计算
   */
  getPageHeight(ws: PrintWorkspace): number {
    return getTrimHeight(ws.trim_size);
  }

  getSheetWidth(ws: PrintWorkspace): number {
    return getTrimWidth(ws.output_sheet_size ?? "A4");
  }

  getSheetHeight(ws: PrintWorkspace): number {
    return getTrimHeight(ws.output_sheet_size ?? "A4");
  }

  /**
   * 获取拼版预览页面宽度
   *
   * 功能作用：
   * 根据当前 trim_size 和 pageIndex
   * 计算拼版预览中每一页的真实宽度
   *
   * 为什么需要：
   * 拼版页面宽度不是固定值：
   *
   * A4 模式：
   * Page1 = 封面
   * Page2 = 书脊
   * Page3 = 封底
   *
   * A5 / B5 模式：
   * Page1 = 封面 + 书脊
   * Page2 = 封底
   *
   * 删除后的影响：
   * 拼版预览比例会完全错误
   */
  getPreviewPageWidth(ws: PrintWorkspace, pageIndex: number): number {
    const trimWidth = this.getPageWidth(ws);
    const sheetWidth = this.getSheetWidth(ws);
    const spine = ws.spine_width_mm ?? 0;

    if (ws.trim_size === "A4") {
      if (pageIndex === 1) {
        return Math.max(spine, 1);
      }
      return trimWidth;
    }

    return sheetWidth;
  }

  /**
   * 获取预览页面宽高比
   *
   * 功能作用：
   * 生成 CSS aspect-ratio
   *
   * 例如：
   * 148 / 210
   *
   * 为什么需要：
   * preview 页面需要保持真实比例
   *
   * 删除后的影响：
   * preview 页面会变形
   */
  getPageRatio(ws: PrintWorkspace): string {
    const w = this.getSheetWidth(ws);
    const h = this.getSheetHeight(ws);
    return `${w}/${h}`;
  }
}
