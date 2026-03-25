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
 * AI 裁切草稿
 *
 * 用户在 Gemini 裁切弹窗中调整裁切线时，
 * 后端会将当前草稿状态保存到 workspace.ai_crop_draft。
 *
 * 生命周期：
 * - 用户点击"生成跨页"后创建
 * - 用户调整裁切线时更新
 * - 用户点击"保存"后清空，并将结果写入 front_output/spine/back + ai_crop_history
 * - 用户点击"丢弃"后清空
 */
export interface AiCropDraft {
  spread_filename: string;
  spread_size?: { width: number; height: number };
  crop_lines?: { vertical_lines: number[]; horizontal_lines: number[] };
  source_cover_filename?: string | null;
  trim_size?: TrimSize | string;
  spine_width_mm?: number;
  updated_at?: string;
}

/**
 * AI 裁切历史项
 *
 * 每次用户保存裁切结果后，会在 workspace.ai_crop_history 中新增一条记录。
 *
 * 历史项与草稿结构相同，但语义不同：
 * - 草稿是"正在编辑的临时状态"
 * - 历史是"已保存的确定结果"
 */
export interface AiCropHistoryItem extends AiCropDraft {}

export interface SpreadPreviewItem {
  spreadFilename: string;
  imageUrl: string;
  spreadWidth: number;
  spreadHeight: number;
  cropLines: { vertical_lines: number[]; horizontal_lines: number[] };
  sourceCoverUrl: string;
  updatedAt?: string;
}

/**
 * Print Workspace 主结构
 *
 * 代表一本书的拼版工作区。
 *
 * 包含：
 * - 成书参数
 * - 素材信息
 * - AI 裁切状态
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

  /**
   * AI 裁切输出（封面 / 书脊 / 封底）
   *
   * 优先级规则：
   * front_output.selected > cover.selected
   *
   * 即：如果 front_output.selected 存在，则封面显示 front_output.selected；
   * 否则显示 cover.selected。
   */
  front_output?: MaterialSlot;

  /**
   * 预览图路径（合成后的完整封面预览）
   */
  preview_path?: string | null;

  /**
   * PDF 路径（最终生成的 PDF）
   */
  pdf_path?: string | null;

  /**
   * 最后更新时间
   */
  updated_at?: string;

  /**
   * AI 裁切草稿
   */
  ai_crop_draft?: AiCropDraft | null;

  /**
   * AI 裁切历史
   */
  ai_crop_history?: AiCropHistoryItem[];
}
