/*
============================================================

Booklore Print Workspace Dimension Utilities
版本：V1.2R-fix05

模块作用：

该文件提供 Print Workspace 所需的
基础尺寸计算函数。

主要职责：

1 计算书脊宽度
2 获取书籍成书尺寸
3 提供统一尺寸接口

设计原则：

• 所有尺寸单位为 mm
• 所有函数纯函数（Pure Function）
• 不依赖 Angular
• 不依赖 Workspace State

============================================================
*/

/**
 * 成书尺寸类型
 *
 * 当前系统支持三种标准尺寸：
 *
 * A4 = 210 × 297 mm
 * A5 = 148 × 210 mm
 * B5 = 176 × 250 mm
 *
 * 使用 union type 可以：
 *
 * • 防止拼写错误
 * • 提供 IDE 自动补全
 * • 保证类型安全
 */
export type TrimSize = "A4" | "A5" | "B5";

/**
 * 计算书脊宽度
 *
 * 功能作用：
 * 根据页数和纸张厚度计算书脊宽度
 *
 * 计算公式：
 *
 * spine_width = page_count × paper_thickness
 *
 * 为什么需要：
 * 拼版时需要知道书脊宽度
 *
 * 删除后的影响：
 * 书脊无法自动计算
 */
export function calcSpineWidth(pageCount: number, thickness: number): number {
  return pageCount * thickness;
}

/**
 * 获取成书宽度
 *
 * 功能作用：
 * 根据 trim_size 返回书籍页面宽度
 *
 * 单位：
 * mm
 *
 * 为什么需要：
 * 拼版计算需要真实页面尺寸
 *
 * 删除后的影响：
 * preview-engine 无法计算拼版宽度
 */
export function getTrimWidth(trim: TrimSize): number {
  switch (trim) {
    case "A4":
      return 210;

    case "A5":
      return 148;

    case "B5":
      return 176;

    default:
      return 148;
  }
}

/**
 * 获取成书高度
 *
 * 功能作用：
 * 根据 trim_size 返回书籍页面高度
 *
 * 单位：
 * mm
 *
 * 为什么需要：
 * preview 页面比例计算需要高度
 *
 * 删除后的影响：
 * preview 页面比例会错误
 */
export function getTrimHeight(trim: TrimSize): number {
  switch (trim) {
    case "A4":
      return 297;

    case "A5":
      return 210;

    case "B5":
      return 250;

    default:
      return 210;
  }
}

/**
 * 获取完整成书尺寸
 *
 * 功能作用：
 * 返回宽度 + 高度对象
 *
 * 示例返回：
 *
 * {
 *   width: 148,
 *   height: 210
 * }
 *
 * 为什么需要：
 * 某些模块需要同时使用宽度和高度
 *
 * 删除后的影响：
 * 需要分别调用 getTrimWidth / getTrimHeight
 */
export function getTrimSize(trim: TrimSize) {
  return {
    width: getTrimWidth(trim),

    height: getTrimHeight(trim),
  };
}
