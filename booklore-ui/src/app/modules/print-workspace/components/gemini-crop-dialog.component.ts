import { Component, EventEmitter, Input, Output, OnInit, OnDestroy, HostListener, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface CropLine {
  id: string;
  type: 'vertical' | 'horizontal';
  position: number;
  label: string;
  shortLabel: string;
}

@Component({
  selector: 'app-gemini-crop-dialog',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './gemini-crop-dialog.component.html',
  styleUrls: ['./gemini-crop-dialog.component.scss'],
})
export class GeminiCropDialogComponent implements OnInit, OnDestroy, OnChanges {
  @Input() visible = false;
  @Input() spreadImageUrl = '';
  @Input() spreadWidth = 0;
  @Input() spreadHeight = 0;
  @Input() initialLines: any = null;
  @Output() save = new EventEmitter<any>();
  @Output() close = new EventEmitter<void>();

  displayWidth = 0;
  displayHeight = 0;
  scale = 1;

  // 缩放和拖拽相关
  zoom = 1.0;  // 当前缩放级别（0.25 - 4.0）
  panX = 0;    // 画布X偏移
  panY = 0;    // 画布Y偏移
  isPanning = false;  // 是否正在拖拽画布
  panStartX = 0;
  panStartY = 0;
  panStartOffsetX = 0;
  panStartOffsetY = 0;

  lines: CropLine[] = [];
  selectedLineId: string | null = null;
  draggingLineId: string | null = null;
  private frontRightBoundary = 0;

  private dragStartX = 0;
  private dragStartY = 0;
  private dragStartPosition = 0;

  backPreviewUrl = '';
  spinePreviewUrl = '';
  previewLoadFailed = {
    back: false,
    spine: false,
  };
  private sourceImageUrl = '';
  private sourceImage: HTMLImageElement | null = null;
  private sourceImagePromise: Promise<HTMLImageElement> | null = null;
  private previewRenderToken = 0;

  saving = false;

  private readonly minDisplayGap = 8;

  ngOnInit(): void {
    this.syncDisplayMetrics();
    this.initializeLines();
  }

  ngOnDestroy(): void {
    this.onDocumentMouseUp();
    this.revokePreviewUrls();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['spreadImageUrl'] && !changes['spreadImageUrl'].firstChange) {
      this.sourceImage = null;
      this.sourceImagePromise = null;
      this.sourceImageUrl = '';
      this.previewRenderToken++;
    }

    if (changes['visible'] || changes['spreadImageUrl'] || changes['spreadWidth'] || changes['spreadHeight'] || changes['initialLines']) {
      this.syncDisplayMetrics();
      if (this.visible) {
        this.initializeLines();
        this.updatePreviews();
      }
    }
  }

  private syncDisplayMetrics(): void {
    if (!this.spreadWidth || !this.spreadHeight) {
      this.displayWidth = 0;
      this.displayHeight = 0;
      this.scale = 1;
      return;
    }

    const maxWidth = 1120;
    const maxHeight = 720;
    const scaleX = maxWidth / this.spreadWidth;
    const scaleY = maxHeight / this.spreadHeight;
    this.scale = Math.min(scaleX, scaleY, 1);
    this.displayWidth = Math.round(this.spreadWidth * this.scale);
    this.displayHeight = Math.round(this.spreadHeight * this.scale);
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

    this.frontRightBoundary = Math.round(vLines[3] * this.scale);

    this.lines = [
      { id: 'v1', type: 'vertical', position: Math.round(vLines[0] * this.scale), label: '封底左边界', shortLabel: '封底左' },
      { id: 'v2', type: 'vertical', position: Math.round(vLines[1] * this.scale), label: '封底/书脊分界线', shortLabel: '共享线' },
      { id: 'v3', type: 'vertical', position: Math.round(vLines[2] * this.scale), label: '书脊右边界', shortLabel: '书脊右' },
      { id: 'h1', type: 'horizontal', position: Math.round(hLines[0] * this.scale), label: '上边界', shortLabel: '上边界' },
      { id: 'h2', type: 'horizontal', position: Math.round(hLines[1] * this.scale), label: '下边界', shortLabel: '下边界' },
    ];

    this.normalizeLinePositions();
  }

  getLineStyle(line: CropLine): any {
    const isSelected = this.selectedLineId === line.id;
    const isDragging = this.draggingLineId === line.id;
    const isHorizontal = line.type === 'horizontal';
    const activeColor = isHorizontal ? '#f59e0b' : '#4f8fff';
    const idleColor = isHorizontal ? 'rgba(245, 158, 11, 0.7)' : 'rgba(79, 143, 255, 0.72)';

    if (line.type === 'vertical') {
      return {
        left: `${line.position}px`,
        top: 0,
        height: '100%',
        width: '4px',
        cursor: 'ew-resize',
        transform: 'translateX(-2px)',
        backgroundColor: isSelected || isDragging ? activeColor : idleColor,
        boxShadow: isSelected || isDragging ? '0 0 12px rgba(79, 143, 255, 0.95)' : '0 0 0 1px rgba(79, 143, 255, 0.18)',
      };
    }

    return {
      top: `${line.position}px`,
      left: 0,
      width: '100%',
      height: '4px',
      cursor: 'ns-resize',
      transform: 'translateY(-2px)',
      backgroundColor: isSelected || isDragging ? activeColor : idleColor,
      boxShadow: isSelected || isDragging ? '0 0 12px rgba(245, 158, 11, 0.9)' : '0 0 0 1px rgba(245, 158, 11, 0.18)',
    };
  }

  get selectedLineLabel(): string {
    return this.lines.find((line) => line.id === this.selectedLineId)?.label || '未选中分界线';
  }

  onPreviewImageError(type: 'back' | 'spine'): void {
    this.previewLoadFailed[type] = true;
    if (type === 'back') {
      this.backPreviewUrl = '';
    } else {
      this.spinePreviewUrl = '';
    }
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

    const nextPosition = line.type === 'vertical'
      ? this.dragStartPosition + (event.clientX - this.dragStartX)
      : this.dragStartPosition + (event.clientY - this.dragStartY);

    this.setLinePosition(line, nextPosition);
    this.updatePreviews();
  };

  private onDocumentMouseUp = (): void => {
    this.draggingLineId = null;
    document.removeEventListener('mousemove', this.onDocumentMouseMove);
    document.removeEventListener('mouseup', this.onDocumentMouseUp);
  };

  onCanvasClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('crop-canvas')) {
      this.selectedLineId = null;
    }
  }

  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (!this.visible || !this.selectedLineId) return;

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
    this.updatePreviews();
  }

  private setLinePosition(line: CropLine, nextPosition: number): void {
    line.position = this.clampLinePosition(line, nextPosition);
    this.normalizeLinePositions();
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

    const left = this.lines.find((item) => item.id === 'v1')?.position ?? 0;
    const middle = this.lines.find((item) => item.id === 'v2')?.position ?? Math.round(this.displayWidth / 2);
    const right = this.lines.find((item) => item.id === 'v3')?.position ?? this.displayWidth;
    const maxRight = Math.min(this.frontRightBoundary - this.minDisplayGap, this.displayWidth);

    if (line.id === 'v1') {
      return Math.max(0, Math.min(middle - this.minDisplayGap, nextPosition));
    }
    if (line.id === 'v2') {
      return Math.max(left + this.minDisplayGap, Math.min(right - this.minDisplayGap, nextPosition));
    }
    return Math.max(middle + this.minDisplayGap, Math.min(maxRight, nextPosition));
  }

  private normalizeLinePositions(): void {
    const v1 = this.lines.find((line) => line.id === 'v1');
    const v2 = this.lines.find((line) => line.id === 'v2');
    const v3 = this.lines.find((line) => line.id === 'v3');
    const h1 = this.lines.find((line) => line.id === 'h1');
    const h2 = this.lines.find((line) => line.id === 'h2');

    if (v1 && v2 && v3) {
      const maxRight = Math.min(this.frontRightBoundary - this.minDisplayGap, this.displayWidth);
      v1.position = Math.max(0, Math.min(v1.position, maxRight - this.minDisplayGap * 2));
      v2.position = Math.max(v1.position + this.minDisplayGap, Math.min(v2.position, maxRight - this.minDisplayGap));
      v3.position = Math.max(v2.position + this.minDisplayGap, Math.min(v3.position, maxRight));
    }

    if (h1 && h2) {
      h1.position = Math.max(0, Math.min(h1.position, this.displayHeight - this.minDisplayGap));
      h2.position = Math.max(h1.position + this.minDisplayGap, Math.min(h2.position, this.displayHeight));
    }
  }

  private getSaveLines(): { vertical_lines: number[]; horizontal_lines: number[] } {
    const v1 = this.lines.find((line) => line.id === 'v1')?.position ?? 0;
    const v2 = this.lines.find((line) => line.id === 'v2')?.position ?? 0;
    const v3 = this.lines.find((line) => line.id === 'v3')?.position ?? 0;
    const h1 = this.lines.find((line) => line.id === 'h1')?.position ?? 0;
    const h2 = this.lines.find((line) => line.id === 'h2')?.position ?? 0;

    return {
      vertical_lines: [v1, v2, v3, this.frontRightBoundary].map((value) => Math.round(value / this.scale)),
      horizontal_lines: [h1, h2].map((value) => Math.round(value / this.scale)),
    };
  }

  private updatePreviews(): void {
    const { vertical_lines: vLines, horizontal_lines: hLines } = this.getSaveLines();

    if (vLines.length !== 4 || hLines.length !== 2) return;

    this.previewLoadFailed.back = false;
    this.previewLoadFailed.spine = false;

    const renderToken = ++this.previewRenderToken;
    this.getSourceImage()
      .then((img) => {
        if (renderToken !== this.previewRenderToken) {
          return;
        }

        this.backPreviewUrl = this.cropImageRegion(img, vLines[0], hLines[0], vLines[1], hLines[1]);
        this.spinePreviewUrl = this.cropImageRegion(img, vLines[1], hLines[0], vLines[2], hLines[1]);
      })
      .catch(() => {
        if (renderToken !== this.previewRenderToken) {
          return;
        }
        this.previewLoadFailed.back = true;
        this.previewLoadFailed.spine = true;
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
    this.saving = true;

    this.save.emit({
      ...payload,
      callback: () => {
        this.saving = false;
        this.onClose();
      },
    });
  }

  onClose(): void {
    this.onDocumentMouseUp();
    this.onStopPanning();
    this.revokePreviewUrls();
    this.selectedLineId = null;
    this.draggingLineId = null;
    this.zoom = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.close.emit();
  }

  /**
   * 滚轮缩放
   */
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
   * 开始拖拽画布（鼠标中键或空格+左键）
   */
  onCanvasMouseDown(event: MouseEvent): void {
    // 空格+左键 或 中键拖拽画布
    if ((event.button === 0 && event.shiftKey) || event.button === 1) {
      event.preventDefault();
      event.stopPropagation();
      this.startPanning(event);
      return;
    }

    // 左键点击空白区域取消选中
    if (event.button === 0 && (event.target as HTMLElement).classList.contains('crop-canvas')) {
      this.selectedLineId = null;
    }
  }

  private startPanning(event: MouseEvent): void {
    this.isPanning = true;
    this.panStartX = event.clientX;
    this.panStartY = event.clientY;
    this.panStartOffsetX = this.panX;
    this.panStartOffsetY = this.panY;

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
  getCanvasContainerStyle(): any {
    return {
      transform: `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`,
      transformOrigin: '0 0',
      width: `${this.displayWidth}px`,
      height: `${this.displayHeight}px`,
    };
  }

  private revokePreviewUrls(): void {
    if (this.backPreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.backPreviewUrl);
    }
    if (this.spinePreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.spinePreviewUrl);
    }
    this.backPreviewUrl = '';
    this.spinePreviewUrl = '';
    this.previewLoadFailed.back = false;
    this.previewLoadFailed.spine = false;
    this.sourceImage = null;
    this.sourceImagePromise = null;
    this.sourceImageUrl = '';
    this.previewRenderToken++;
  }
}
