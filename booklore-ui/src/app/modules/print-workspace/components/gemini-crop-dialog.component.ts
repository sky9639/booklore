import { Component, EventEmitter, Input, Output, OnInit, OnDestroy, HostListener, OnChanges, SimpleChanges, ViewChild, ElementRef, AfterViewInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import type { SpreadPreviewItem } from '../models/workspace.model';

interface CropLine {
  id: string;
  type: 'vertical' | 'horizontal';
  position: number;
  label: string;
  shortLabel: string;
}

interface CropSaveEvent {
  vertical_lines: number[];
  horizontal_lines: number[];
}

@Component({
  selector: 'app-gemini-crop-dialog',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './gemini-crop-dialog.component.html',
  styleUrls: ['./gemini-crop-dialog.component.scss'],
})
export class GeminiCropDialogComponent implements OnInit, OnDestroy, OnChanges, AfterViewInit {
  @Input() visible = false;
  @Input() generating = false;
  @Input() generateButtonText = 'AI生图';
  @Input() generateErrorMessage = '';
  @Input() spreadImageUrl = '';
  @Input() spreadWidth = 0;
  @Input() spreadHeight = 0;
  @Input() initialLines: { vertical_lines?: number[]; horizontal_lines?: number[]; vertical?: number[]; horizontal?: number[] } | null = null;
  @Input() historyItems: SpreadPreviewItem[] = [];
  @Input() activeSpreadFilename = '';
  @Input() saving = false;
  @Output() generate = new EventEmitter<void>();
  @Output() openConfig = new EventEmitter<void>();
  @Output() save = new EventEmitter<CropSaveEvent>();
  @Output() close = new EventEmitter<void>();
  @Output() historySelect = new EventEmitter<string>();
  @Output() historyDelete = new EventEmitter<string>();

  @ViewChild('canvasShell', { static: false }) canvasShellRef?: ElementRef<HTMLDivElement>;

  displayWidth = 0;
  displayHeight = 0;
  scale = 1;
  private cachedSpreadKey = '';
  private cachedScale = 1;

  // 缩放和拖拽相关
  zoom = 1.0;  // 当前缩放级别（0.25 - 4.0）
  panX = 0;    // 画布X偏移
  panY = 0;    // 画布Y偏移
  isPanning = false;  // 是否正在拖拽画布
  panStartX = 0;
  panStartY = 0;
  panStartOffsetX = 0;
  panStartOffsetY = 0;
  blankAreaPointerDown = false;
  blankAreaPanStarted = false;
  blankAreaStartX = 0;
  blankAreaStartY = 0;

  lines: CropLine[] = [];
  selectedLineId: string | null = null;
  draggingLineId: string | null = null;

  private dragStartX = 0;
  private dragStartY = 0;
  private dragStartPosition = 0;

  backPreviewUrl = '';
  spinePreviewUrl = '';
  frontPreviewUrl = '';
  private sourceImageUrl = '';
  private sourceImage: HTMLImageElement | null = null;
  private sourceImagePromise: Promise<HTMLImageElement> | null = null;
  private previewRenderToken = 0;
  private refreshScheduled = false;
  private previewUpdateScheduled = false;
  private lastPreviewKey = '';

  private readonly minDisplayGap = 8;
  private readonly blankAreaDragThreshold = 5;

  constructor() {}

  ngOnInit(): void {
    this.syncDisplayMetrics();
    this.initializeLines();
  }

  ngAfterViewInit(): void {
    if (this.visible) {
      this.scheduleVisibleRefresh();
    }
  }

  ngOnDestroy(): void {
    this.onDocumentMouseUp();
    this.resetBlankAreaPointerState();
    this.onStopPanning();
    this.revokePreviewUrls();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['spreadImageUrl'] && !changes['spreadImageUrl'].firstChange) {
      this.sourceImage = null;
      this.sourceImagePromise = null;
      this.sourceImageUrl = '';
      this.previewRenderToken++;
      this.lastPreviewKey = '';
      this.zoom = 1.0;
      this.panX = 0;
      this.panY = 0;
    }

    if (changes['spreadWidth'] || changes['spreadHeight']) {
      this.invalidateScaleCache();
    }

    if (changes['visible'] || changes['spreadImageUrl'] || changes['spreadWidth'] || changes['spreadHeight'] || changes['initialLines']) {
      if (this.visible) {
        this.scheduleVisibleRefresh();
      }
    }
  }

  @HostListener('window:resize')
  onWindowResize(): void {
    if (this.visible) {
      this.invalidateScaleCache();
      this.scheduleVisibleRefresh();
    }
  }

  private invalidateScaleCache(): void {
    this.cachedSpreadKey = '';
    this.cachedScale = 1;
  }

  private scheduleVisibleRefresh(): void {
    if (this.refreshScheduled) {
      return;
    }

    this.refreshScheduled = true;
    requestAnimationFrame(() => {
      this.refreshScheduled = false;
      if (!this.visible) {
        return;
      }

      this.syncDisplayMetrics();

      if ((!this.spreadWidth || !this.spreadHeight) && this.spreadImageUrl) {
        this.loadImageDimensionsAndRefresh();
        return;
      }

      this.initializeLines();
      this.updatePreviews();
    });
  }

  private async loadImageDimensionsAndRefresh(): Promise<void> {
    try {
      const img = await this.getSourceImage();
      const spreadWidth = this.spreadWidth || img.naturalWidth || img.width;
      const spreadHeight = this.spreadHeight || img.naturalHeight || img.height;
      if (!spreadWidth || !spreadHeight) {
        return;
      }
      this.invalidateScaleCache();
      this.syncDisplayMetrics(spreadWidth, spreadHeight);
      this.initializeLines();
      this.updatePreviews();
    } catch {
      // ignore dimension fallback failure and keep current empty state
    }
  }


  private syncDisplayMetrics(spreadWidth = this.spreadWidth, spreadHeight = this.spreadHeight): void {
    if (!spreadWidth || !spreadHeight) {
      this.displayWidth = 0;
      this.displayHeight = 0;
      this.scale = 1;
      this.invalidateScaleCache();
      return;
    }

    const currentSpreadKey = `${spreadWidth}x${spreadHeight}`;

    if (this.cachedSpreadKey === currentSpreadKey && this.cachedScale > 0) {
      this.scale = this.cachedScale;
      this.displayWidth = Math.round(spreadWidth * this.scale);
      this.displayHeight = Math.round(spreadHeight * this.scale);
      return;
    }

    let availableWidth = 800;
    let availableHeight = 600;

    if (this.canvasShellRef?.nativeElement) {
      const rect = this.canvasShellRef.nativeElement.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        availableWidth = Math.max(rect.width - 40, 400);
        availableHeight = Math.max(rect.height - 40, 400);
      } else {
        availableWidth = Math.max(window.innerWidth * 0.6, 800);
        availableHeight = Math.max(window.innerHeight * 0.7, 600);
      }
    } else {
      availableWidth = Math.max(window.innerWidth * 0.6, 800);
      availableHeight = Math.max(window.innerHeight * 0.7, 600);
    }

    const scaleX = availableWidth / spreadWidth;
    const scaleY = availableHeight / spreadHeight;

    this.scale = Math.min(scaleX, scaleY);
    this.cachedSpreadKey = currentSpreadKey;
    this.cachedScale = this.scale;
    this.displayWidth = Math.round(spreadWidth * this.scale);
    this.displayHeight = Math.round(spreadHeight * this.scale);
  }

  private initializeLines(): void {
    if (!this.displayWidth || !this.displayHeight) return;

    const initialVerticalLines = this.initialLines?.vertical_lines?.length ? this.initialLines.vertical_lines : this.initialLines?.vertical;
    const initialHorizontalLines = this.initialLines?.horizontal_lines?.length ? this.initialLines.horizontal_lines : this.initialLines?.horizontal;

    const vLines = initialVerticalLines?.length === 4 ? initialVerticalLines : [
      Math.floor(this.spreadWidth * 0.22),
      Math.floor(this.spreadWidth * 0.48),
      Math.floor(this.spreadWidth * 0.56),
      Math.floor(this.spreadWidth * 0.82),
    ];

    const hLines = initialHorizontalLines?.length === 2 ? initialHorizontalLines : [
      Math.floor(this.spreadHeight * 0.1),
      Math.floor(this.spreadHeight * 0.9),
    ];

    this.lines = [
      { id: 'v1', type: 'vertical', position: Math.round(vLines[0] * this.scale), label: '封底左边界', shortLabel: '封底左' },
      { id: 'v2', type: 'vertical', position: Math.round(vLines[1] * this.scale), label: '封底/书脊分界线', shortLabel: '共享线' },
      { id: 'v3', type: 'vertical', position: Math.round(vLines[2] * this.scale), label: '书脊右边界', shortLabel: '书脊右' },
      { id: 'v4', type: 'vertical', position: Math.round(vLines[3] * this.scale), label: '前封右边界', shortLabel: '前封右' },
      { id: 'h1', type: 'horizontal', position: Math.round(hLines[0] * this.scale), label: '上边界', shortLabel: '上边界' },
      { id: 'h2', type: 'horizontal', position: Math.round(hLines[1] * this.scale), label: '下边界', shortLabel: '下边界' },
    ];

    this.normalizeLinePositions();
  }

  get selectedLineLabel(): string {
    return this.lines.find((line) => line.id === this.selectedLineId)?.label || '未选中分界线';
  }

  selectHistory(spreadFilename: string): void {
    if (!spreadFilename || spreadFilename === this.activeSpreadFilename) {
      return;
    }
    this.historySelect.emit(spreadFilename);
  }

  deleteHistory(spreadFilename: string, event: Event): void {
    event.stopPropagation();
    if (!spreadFilename) {
      return;
    }
    const confirmed = confirm('确认删除这张历史展开图吗？删除后无法恢复。');
    if (!confirmed) {
      return;
    }
    this.historyDelete.emit(spreadFilename);
  }

  get previewStatusText(): string {
    if (this.generating) {
      return '正在生成新的 AI 展开图';
    }
    if (this.saving) {
      return '正在保存裁切结果';
    }
    if (this.generateErrorMessage) {
      return '生成失败，请调整配置后重试';
    }
    if (this.spreadImageUrl) {
      return '拖动裁切线时，右侧预览会实时更新';
    }
    return '暂无展开图，请先点击 AI生图';
  }

  get hasPreviewImage(): boolean {
    return !!this.spreadImageUrl;
  }

  onPreviewImageError(type: 'back' | 'spine' | 'front'): void {
    if (type === 'back') {
      this.backPreviewUrl = '';
    } else if (type === 'spine') {
      this.spinePreviewUrl = '';
    } else {
      this.frontPreviewUrl = '';
    }
  }

  onGenerate(): void {
    if (this.generating) {
      return;
    }
    this.generate.emit();
  }

  onOpenConfig(): void {
    this.openConfig.emit();
  }

  private async getSourceImage(): Promise<HTMLImageElement> {
    if (!this.spreadImageUrl) {
      throw new Error('spreadImageUrl is empty');
    }

    if (this.sourceImage && this.sourceImageUrl === this.spreadImageUrl) {
      return this.sourceImage;
    }

    if (this.sourceImagePromise && this.sourceImageUrl === this.spreadImageUrl) {
      return this.sourceImagePromise;
    }

    this.sourceImageUrl = this.spreadImageUrl;
    this.sourceImage = null;
    this.sourceImagePromise = new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        this.sourceImage = img;
        resolve(img);
      };
      img.onerror = () => {
        this.sourceImagePromise = null;
        reject(new Error('Failed to load spread image'));
      };
      img.src = this.spreadImageUrl;
    });

    return this.sourceImagePromise;
  }

  onLineMouseDown(event: MouseEvent, line: CropLine): void {
    event.preventDefault();
    event.stopPropagation();

    this.draggingLineId = line.id;
    this.selectedLineId = line.id;
    this.dragStartX = event.clientX;
    this.dragStartY = event.clientY;
    this.dragStartPosition = line.position;

    document.addEventListener('mousemove', this.onDocumentMouseMove);
    document.addEventListener('mouseup', this.onDocumentMouseUp);
  }

  private onDocumentMouseMove = (event: MouseEvent): void => {
    if (!this.draggingLineId) return;

    const line = this.lines.find((l) => l.id === this.draggingLineId);
    if (!line) return;

    const delta = line.type === 'vertical'
      ? (event.clientX - this.dragStartX) / this.zoom
      : (event.clientY - this.dragStartY) / this.zoom;

    const nextPosition = this.dragStartPosition + delta;

    this.setLinePosition(line, nextPosition);
    this.schedulePreviewUpdate();
  };

  private onDocumentMouseUp = (): void => {
    this.draggingLineId = null;
    document.removeEventListener('mousemove', this.onDocumentMouseMove);
    document.removeEventListener('mouseup', this.onDocumentMouseUp);
  };

  private resetBlankAreaPointerState(): void {
    this.blankAreaPointerDown = false;
    this.blankAreaPanStarted = false;
    this.blankAreaStartX = 0;
    this.blankAreaStartY = 0;
    document.removeEventListener('mousemove', this.onBlankAreaMouseMove);
    document.removeEventListener('mouseup', this.onBlankAreaMouseUp);
  }

  private onBlankAreaMouseMove = (event: MouseEvent): void => {
    if (!this.blankAreaPointerDown || this.blankAreaPanStarted) {
      return;
    }

    const dx = event.clientX - this.blankAreaStartX;
    const dy = event.clientY - this.blankAreaStartY;
    if (Math.hypot(dx, dy) < this.blankAreaDragThreshold) {
      return;
    }

    this.blankAreaPanStarted = true;
    this.panStartX = this.blankAreaStartX;
    this.panStartY = this.blankAreaStartY;
    this.panStartOffsetX = this.panX;
    this.panStartOffsetY = this.panY;
    this.startPanning(event);
    this.onPanningMouseMove(event);
  };

  private onBlankAreaMouseUp = (): void => {
    const shouldDeselect = this.blankAreaPointerDown && !this.blankAreaPanStarted;
    this.resetBlankAreaPointerState();
    if (shouldDeselect) {
      this.selectedLineId = null;
    }
  };

  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (!this.visible) return;

    // Esc 键取消选中
    if (event.key === 'Escape') {
      this.selectedLineId = null;
      return;
    }

    if (!this.selectedLineId) return;

    const line = this.lines.find((l) => l.id === this.selectedLineId);
    if (!line) return;

    const step = event.shiftKey ? 10 : 1;
    let nextPosition: number | null = null;

    if (line.type === 'vertical') {
      if (event.key === 'ArrowLeft') {
        nextPosition = line.position - step;
      } else if (event.key === 'ArrowRight') {
        nextPosition = line.position + step;
      }
    } else {
      if (event.key === 'ArrowUp') {
        nextPosition = line.position - step;
      } else if (event.key === 'ArrowDown') {
        nextPosition = line.position + step;
      }
    }

    if (nextPosition === null) {
      return;
    }

    event.preventDefault();
    this.setLinePosition(line, nextPosition);
    this.schedulePreviewUpdate();
  }

  private setLinePosition(line: CropLine, nextPosition: number): void {
    const previous = line.position;
    line.position = this.clampLinePosition(line, nextPosition);
    this.normalizeLinePositions();
    if (Math.abs(line.position - previous) < 0.01) {
      return;
    }
  }

  private clampLinePosition(line: CropLine, nextPosition: number): number {
    if (line.type === 'horizontal') {
      const top = this.lines.find((item) => item.id === 'h1')?.position ?? 0;
      const bottom = this.lines.find((item) => item.id === 'h2')?.position ?? this.displayHeight;

      if (line.id === 'h1') {
        return Math.max(0, Math.min(bottom - this.minDisplayGap, nextPosition));
      }

      return Math.max(top + this.minDisplayGap, Math.min(this.displayHeight, nextPosition));
    }

    return Math.max(0, Math.min(this.displayWidth, nextPosition));
  }

  private normalizeLinePositions(): void {
    const h1 = this.lines.find((line) => line.id === 'h1');
    const h2 = this.lines.find((line) => line.id === 'h2');

    const verticalLines = this.lines.filter((item) => item.type === 'vertical').sort((a, b) => a.position - b.position);

    for (let i = 0; i < verticalLines.length; i++) {
      const line = verticalLines[i];
      line.position = Math.max(0, Math.min(this.displayWidth, line.position));

      if (i > 0) {
        const prevLine = verticalLines[i - 1];
        if (line.position < prevLine.position + this.minDisplayGap) {
          line.position = prevLine.position + this.minDisplayGap;
        }
      }
    }

    if (h1 && h2) {
      h1.position = Math.max(0, Math.min(h1.position, this.displayHeight - this.minDisplayGap));
      h2.position = Math.max(h1.position + this.minDisplayGap, Math.min(h2.position, this.displayHeight));
    }
  }

  private getOrderedCropBounds(): { verticalLines: number[]; horizontalLines: number[] } {
    const verticalLines = this.lines
      .filter((line) => line.type === 'vertical')
      .map((line) => line.position)
      .sort((a, b) => a - b);

    const horizontalLines = this.lines
      .filter((line) => line.type === 'horizontal')
      .map((line) => line.position)
      .sort((a, b) => a - b);

    return { verticalLines, horizontalLines };
  }

  private getSaveLines(): { vertical_lines: number[]; horizontal_lines: number[] } {
    const { verticalLines, horizontalLines } = this.getOrderedCropBounds();

    return {
      vertical_lines: verticalLines.map((value) => Math.round(value / this.scale)),
      horizontal_lines: horizontalLines.map((value) => Math.round(value / this.scale)),
    };
  }

  private schedulePreviewUpdate(): void {
    if (this.previewUpdateScheduled) {
      return;
    }

    this.previewUpdateScheduled = true;
    requestAnimationFrame(() => {
      this.previewUpdateScheduled = false;
      if (!this.visible) {
        return;
      }
      this.updatePreviews();
    });
  }

  private updatePreviews(): void {
    const { vertical_lines: vLines, horizontal_lines: hLines } = this.getSaveLines();

    if (vLines.length !== 4 || hLines.length !== 2 || !this.spreadImageUrl) return;

    const previewKey = `${this.spreadImageUrl}|${vLines.join(',')}|${hLines.join(',')}`;
    if (previewKey === this.lastPreviewKey) {
      return;
    }
    this.lastPreviewKey = previewKey;

    const renderToken = ++this.previewRenderToken;
    this.getSourceImage()
      .then((img) => {
        if (renderToken !== this.previewRenderToken) {
          return;
        }

        this.backPreviewUrl = this.cropImageRegion(img, vLines[0], hLines[0], vLines[1], hLines[1]);
        this.spinePreviewUrl = this.cropImageRegion(img, vLines[1], hLines[0], vLines[2], hLines[1]);
        this.frontPreviewUrl = this.cropImageRegion(img, vLines[2], hLines[0], vLines[3], hLines[1]);
      })
      .catch(() => {
        if (renderToken !== this.previewRenderToken) {
          return;
        }
        this.backPreviewUrl = '';
        this.spinePreviewUrl = '';
        this.frontPreviewUrl = '';
      });
  }

  private cropImageRegion(img: HTMLImageElement, x1: number, y1: number, x2: number, y2: number): string {
    const width = Math.max(x2 - x1, 1);
    const height = Math.max(y2 - y1, 1);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext('2d');
    if (!ctx) return '';

    ctx.drawImage(img, x1, y1, width, height, 0, 0, width, height);
    return canvas.toDataURL('image/png');
  }

  onSave(): void {
    const payload = this.getSaveLines();
    this.save.emit(payload);
  }

  onClose(): void {
    this.resetInteractionState(false);
    this.close.emit();
  }

  private resetInteractionState(clearPreviews: boolean): void {
    this.onDocumentMouseUp();
    this.resetBlankAreaPointerState();
    this.onStopPanning();
    if (clearPreviews) {
      this.revokePreviewUrls();
    }
    this.selectedLineId = null;
    this.draggingLineId = null;
    this.zoom = 1.0;
    this.panX = 0;
    this.panY = 0;
  }

  onCanvasWheel(event: WheelEvent): void {
    event.preventDefault();
    event.stopPropagation();

    const delta = event.deltaY > 0 ? -0.1 : 0.1;
    const newZoom = Math.max(0.25, Math.min(4.0, this.zoom + delta));

    // 以鼠标位置为中心缩放
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    // 计算缩放前后鼠标在画布上的相对位置
    const beforeX = (mouseX - this.panX) / this.zoom;
    const beforeY = (mouseY - this.panY) / this.zoom;

    this.zoom = newZoom;

    // 调整偏移，保持鼠标位置不变
    this.panX = mouseX - beforeX * this.zoom;
    this.panY = mouseY - beforeY * this.zoom;
  }

  /**
   * 开始拖拽画布（空白区域左键直接拖拽、Shift + 左键或鼠标中键）
   */
  onCanvasMouseDown(event: MouseEvent): void {
    if (this.draggingLineId) {
      return;
    }

    if (event.button !== 0 && event.button !== 1) {
      return;
    }

    const target = event.target as HTMLElement;
    const lineElement = target.closest('.crop-line');
    const isCanvasSurface = !!target.closest('.crop-canvas');

    if (lineElement || !isCanvasSurface) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.resetBlankAreaPointerState();
    this.startPanning(event);
  }

  private startPanning(event: MouseEvent): void {
    this.isPanning = true;

    if (!this.blankAreaPanStarted) {
      this.panStartX = event.clientX;
      this.panStartY = event.clientY;
      this.panStartOffsetX = this.panX;
      this.panStartOffsetY = this.panY;
    }

    document.addEventListener('mousemove', this.onPanningMouseMove);
    document.addEventListener('mouseup', this.onStopPanning);
  }

  private onPanningMouseMove = (event: MouseEvent): void => {
    if (!this.isPanning) return;

    const dx = event.clientX - this.panStartX;
    const dy = event.clientY - this.panStartY;

    this.panX = this.panStartOffsetX + dx;
    this.panY = this.panStartOffsetY + dy;
  };

  private onStopPanning = (): void => {
    this.isPanning = false;
    this.resetBlankAreaPointerState();
    document.removeEventListener('mousemove', this.onPanningMouseMove);
    document.removeEventListener('mouseup', this.onStopPanning);
  };

  /**
   * 重置缩放和偏移
   */
  resetZoom(): void {
    this.zoom = 1.0;
    this.panX = 0;
    this.panY = 0;
  }

  /**
   * 获取画布容器样式（应用缩放和偏移）
   */
  get canvasTransform(): string {
    return `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
  }

  private revokePreviewUrls(): void {
    if (this.backPreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.backPreviewUrl);
    }
    if (this.spinePreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.spinePreviewUrl);
    }
    if (this.frontPreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.frontPreviewUrl);
    }
    this.backPreviewUrl = '';
    this.spinePreviewUrl = '';
    this.frontPreviewUrl = '';
    this.lastPreviewKey = '';
    this.sourceImage = null;
    this.sourceImagePromise = null;
    this.sourceImageUrl = '';
    this.previewRenderToken++;
  }
}
