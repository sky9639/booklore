/*
============================================================
Booklore Print Workspace Material Slot Component
版本：V1.5

变更（相较 V1.4）：
- 移除卡片底部独立 AI 生成按钮（thumb-ai）
- 移除 aiGenerating 状态、onAiGenerate() 方法
- 移除 aiGenerated Output 事件
- AI 生成统一由父组件标题行按钮触发
- 清理相关 CSS（.thumb-ai / .ai-spinner / @keyframes aiSpin）
============================================================
*/

import { Component, Input, Output, EventEmitter } from "@angular/core";
import { CommonModule } from "@angular/common";
import {
  MaterialService,
  MaterialType,
  UploadMaterialType,
} from "../services/material.service";
import { WorkspaceState } from "../services/print.service";

interface MaterialHistoryItem {
  filename: string;
  type: MaterialType;
  label: string;
  active: boolean;
}

@Component({
  selector: "app-material-slot",
  standalone: true,
  imports: [CommonModule],
  styles: [
    `
      .material-card {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 14px;
        border-radius: 10px;
        border: 1px solid #24324a;
        background: #0f1a2b;
        height: 100%;
        box-sizing: border-box;
        position: relative;
      }

      .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-shrink: 0;
      }

      .card-title-wrap {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex-wrap: wrap;
      }

      .card-title {
        font-size: 14px;
        font-weight: 600;
        color: #e6edf3;
      }

      .title-badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        color: #9fc2ff;
        background: rgba(79, 124, 255, 0.14);
        border: 1px solid rgba(79, 124, 255, 0.28);
        white-space: nowrap;
      }

      .spine-badge {
        display: block;
        text-align: center;
        font-size: 11px;
        color: #6da3e8;
        background: #1a2f4a;
        border: 1px solid #2a4a70;
        border-radius: 4px;
        padding: 2px 10px;
        font-family: monospace;
        white-space: nowrap;
        width: 60px;
        align-self: center;
        box-sizing: border-box;
        margin-bottom: -6px;
      }

      .preview-box {
        position: relative;
        width: 100%;
        flex: 1;
        min-height: 120px;
        max-height: 200px;
        overflow: hidden;
        background: #0c1624;
        border-radius: 6px;
      }

      .preview-box img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
        object-position: center;
      }

      .preview-box.narrow {
        width: 60px;
        align-self: center;
      }

      .preview-overlay {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.35);
        opacity: 0;
        transition: opacity 0.2s;
        z-index: 2;
        cursor: zoom-in;
      }
      .preview-box:hover .preview-overlay {
        opacity: 1;
      }
      .preview-overlay i {
        font-size: 22px;
        color: white;
        background: rgba(0, 0, 0, 0.55);
        border-radius: 50%;
        padding: 8px;
      }

      .preview-placeholder {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 8px;
        color: #3d5270;
      }
      .preview-placeholder i {
        font-size: 28px;
      }
      .preview-placeholder span {
        font-size: 12px;
      }

      .history-strip {
        display: flex;
        gap: 8px;
        height: 80px;
        flex-shrink: 0;
        align-items: center;
        overflow-x: auto;
        scrollbar-width: none;
        -ms-overflow-style: none;
        padding: 4px 0;
      }

      .history-strip.roomy {
        margin-top: 8px;
      }

      .history-strip::-webkit-scrollbar {
        display: none;
      }

      .thumb-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
      }

      .thumb-wrapper {
        width: 68px;
        height: 68px;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid #2b3b55;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        flex-shrink: 0;
        cursor: pointer;
        transition:
          border-color 0.15s,
          transform 0.15s;
      }

      .thumb-wrapper img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
      }

      .thumb-wrapper:hover {
        border-color: #4f7cff;
        transform: translateY(-1px);
      }
      .thumb-wrapper.active {
        border: 2px solid #4f7cff;
      }

      .thumb-label {
        font-size: 10px;
        color: #7f93b0;
        text-align: center;
        white-space: nowrap;
      }

      .thumb-overlay-delete {
        position: absolute;
        top: 3px;
        right: 3px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: rgba(0, 0, 0, 0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        transition: opacity 0.15s;
        z-index: 2;
      }
      .thumb-wrapper:hover .thumb-overlay-delete {
        opacity: 1;
      }
      .thumb-overlay-delete i {
        font-size: 10px;
        color: #ff6b6b;
      }

      .thumb-upload {
        width: 68px;
        height: 68px;
        border-radius: 6px;
        border: 2px dashed #3c4d6b;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #7f93b0;
        cursor: pointer;
        flex-shrink: 0;
        transition:
          border-color 0.15s,
          color 0.15s;
      }
      .thumb-upload:hover {
        border-color: #4f7cff;
        color: #4f7cff;
      }
    `,
  ],

  template: `
    <div class="material-card">
      <div class="card-header">
        <div class="card-title-wrap">
          <span class="card-title">{{ title }}</span>
          <span class="title-badge" *ngIf="$any(this).statusBadge">{{ $any(this).statusBadge }}</span>
        </div>
      </div>

      <span class="spine-badge" *ngIf="type === 'spine'"
        >{{ spineWidth }} mm</span
      >

      <div class="preview-box" [class.narrow]="type === 'spine'">
        <img *ngIf="selected" [src]="url" draggable="false" />
        <div class="preview-placeholder" *ngIf="!selected">
          <i class="pi pi-image"></i>
          <span>暂无素材</span>
        </div>
        <div
          class="preview-overlay"
          *ngIf="selected"
          (click)="onPreviewClick()"
        >
          <i class="pi pi-search-plus"></i>
        </div>
      </div>

      <div class="history-strip" [class.roomy]="type !== 'spine'">
        <div class="thumb-item" *ngFor="let item of normalizedHistory; trackBy: trackHistory">
          <div
            class="thumb-wrapper"
            [class.active]="item.active"
            (click)="select(item)"
          >
            <img
              [src]="material.getAssetUrl(bookId, item.type, item.filename)"
              draggable="false"
            />
            <div class="thumb-overlay-delete" *ngIf="canDelete(item)">
              <i class="pi pi-trash" (click)="delete(item, $event)"></i>
            </div>
          </div>
          <div class="thumb-label" *ngIf="item.label">{{ item.label }}</div>
        </div>

        <div class="thumb-upload" (click)="fileInput.click()">
          <i class="pi pi-plus"></i>
        </div>
      </div>

      <input
        type="file"
        hidden
        #fileInput
        accept="image/png,image/jpeg,image/webp"
        (change)="onFileChange($event)"
      />
    </div>
  `,
})
export class MaterialSlotComponent {
  @Input() title!: string;
  @Input() type!: UploadMaterialType;
  @Input() selected!: string | null;
  @Input() url!: string;
  @Input() history!: Array<string | MaterialHistoryItem>;
  @Input() spineWidth!: number;
  @Input() bookId!: number;
  @Input() statusBadge?: string;
  @Input() historyNote?: string;

  @Output() previewRequest = new EventEmitter<string>();
  @Output() deleted = new EventEmitter<WorkspaceState>();
  @Output() uploaded = new EventEmitter<WorkspaceState>();
  @Output() materialSelected = new EventEmitter<WorkspaceState>();

  constructor(public material: MaterialService) {}

  get normalizedHistory(): MaterialHistoryItem[] {
    return this.history.map(item => {
      if (typeof item === "string") {
        return {
          filename: item,
          type: this.type,
          label: "",
          active: this.selected === item,
        };
      }
      return item;
    });
  }

  onFileChange(event: Event) {
    const input = event.target as HTMLInputElement;
    if (!input.files?.length) return;
    const file = input.files[0];
    this.material.uploadMaterial(this.bookId, this.type, file).subscribe({
      next: (ws) => this.uploaded.emit(ws),
      error: (err) => console.error("Upload failed:", err),
    });
  }

  trackHistory(index: number, item: MaterialHistoryItem) {
    return `${item.type}:${item.filename}`;
  }

  select(item: MaterialHistoryItem): void {
    this.material.selectMaterial(this.bookId, item.type, item.filename).subscribe({
      next: (ws) => this.materialSelected.emit(ws),
      error: (err) => console.error("Select failed:", err),
    });
  }

  canDelete(item: MaterialHistoryItem): boolean {
    return item.type !== "cover";
  }

  delete(item: MaterialHistoryItem, event: Event) {
    event.stopPropagation();
    if (!this.canDelete(item)) return;
    this.material.deleteMaterial(this.bookId, item.type, item.filename).subscribe({
      next: (ws) => this.deleted.emit(ws),
      error: (err) => console.error("Delete failed:", err),
    });
  }

  onPreviewClick() {
    if (this.url) this.previewRequest.emit(this.url);
  }
}
