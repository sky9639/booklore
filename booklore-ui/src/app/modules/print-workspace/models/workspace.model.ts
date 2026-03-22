/*
============================================================
Booklore Print Workspace Model

该文件定义 Print Workspace 的核心数据结构。

设计目标：

1. 保持数据结构简单清晰
2. 与前端 UI 与后端 print-engine 完全一致
3. 所有拼版计算只依赖该结构

数据结构分为两部分：

1 Workspace 基本参数
2 素材管理（封面 / 书脊 / 封底）

============================================================
*/

/**
 * 成书尺寸类型
 *
 * 当前系统支持三种尺寸：
 *
 * A4 = 210 × 297 mm
 * A5 = 148 × 210 mm
 * B5 = 176 × 250 mm
 *
 * 使用 union type 可以：
 * - 保证类型安全
 * - 避免 magic string
 * - 提供 IDE 自动补全
 */
export type TrimSize = "A4" | "A5" | "B5";

/**
 * 素材槽位结构
 *
 * 每种素材（封面 / 书脊 / 封底）都拥有：
 *
 * selected
 * 当前选中的素材
 *
 * history
 * 历史上传素材列表
 */
export interface MaterialSlot {
  /**
   * 当前选中的素材文件名
   */
  selected: string | null;

  /**
   * 历史素材列表
   */
  history: string[];
}

/**
 * Print Workspace 主结构
 *
 * 代表一本书的拼版工作区。
 *
 * 包含：
 * - 成书参数
 * - 素材信息
 */
export interface PrintWorkspace {
  /**
   * 书名
   */
  book_name?: string;

  /**
   * 成书尺寸
   */
  trim_size: TrimSize;

  /**
   * 页数
   */
  page_count: number;

  /**
   * 纸张厚度 (mm)
   */
  paper_thickness: number;

  /**
   * 书脊宽度 (mm)
   *
   * spine_width = page_count × paper_thickness
   */
  spine_width_mm: number;

  /**
   * 封面素材
   */
  cover: MaterialSlot;

  /**
   * 书脊素材
   */
  spine: MaterialSlot;

  /**
   * 封底素材
   */
  back: MaterialSlot;
}
