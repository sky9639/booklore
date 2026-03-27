import { Component, EventEmitter, Input, Output, OnInit, OnChanges, HostListener, ViewChildren, QueryList, ElementRef, AfterViewChecked, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';

/**
 * Gemini AI 配置弹窗组件 V2.0
 *
 * 功能：
 * - 联通参数多组管理（新增/删除/重命名/切换）
 * - 提示词模板多组管理（新增/删除/重命名/切换）
 * - 测试连接
 * - 统一保存
 *
 * 交互设计：
 * - 顶部：联通参数页签组（独立）
 * - 中部：提示词模板页签组（独立）
 * - 底部：状态栏 + 保存按钮
 * - 两组页签互不联动
 * - 页签支持双击重命名、hover 删除、末尾新增
 */

/** 联通参数配置模型 */
interface Profile {
  id: string;
  name: string;
  baseUrl: string;
  apiPath: string;
  apiKey: string;
  model: string;
  timeout: number;
  imageSize?: '1K' | '2K' | '4K';
  imageSizeSupported?: boolean | null;
  imageSizeDetectionStatus?: 'unknown' | 'supported' | 'unsupported' | 'stale';
  imageSizeDetectionFingerprint?: string | null;
}

/** 提示词模板模型 */
interface Template {
  id: string;
  name: string;
  description: string;
  content: string;
  variables?: Array<{ name: string; description: string; example?: string }>;
}

@Component({
  selector: 'app-gemini-config-dialog',
  standalone: true,
  imports: [FormsModule, CommonModule],
  templateUrl: './gemini-config-dialog.component.html',
  styleUrls: ['./gemini-config-dialog.component.scss'],
})
export class GeminiConfigDialogComponent implements OnInit, OnChanges, AfterViewChecked {
  @Input() visible = false;
  @Input() config: any = {};
  @Input() prompts: any = {};
  @Output() save = new EventEmitter<any>();
  @Output() close = new EventEmitter<void>();

  @ViewChildren('profileRenameInput') profileRenameInputs!: QueryList<ElementRef<HTMLInputElement>>;
  @ViewChildren('templateRenameInput') templateRenameInputs!: QueryList<ElementRef<HTMLInputElement>>;

  // ── 常量文案 ──────────────────────────────────────────
  readonly apiPathPlaceholder = '/google/v1/models/{model}';

  // ── 联通参数状态 ──────────────────────────────────────────
  activeProfileId = '';
  profiles: Profile[] = [];
  editingProfileId: string | null = null; // 正在重命名的 profile ID
  editingProfileName = ''; // 重命名输入框内容
  needFocusProfileInput = false; // 标记需要聚焦 profile 输入框
  profileFormData: Profile | null = null; // 表单绑定的临时副本

  // ── 提示词模板状态 ──────────────────────────────────────────
  activeTemplateId = '';
  templates: Template[] = [];
  editingTemplateId: string | null = null; // 正在重命名的 template ID
  editingTemplateName = ''; // 重命名输入框内容
  needFocusTemplateInput = false; // 标记需要聚焦 template 输入框
  templateFormData: Template | null = null; // 表单绑定的临时副本

  // ── 全局状态 ──────────────────────────────────────────
  testing = false;
  testResult = '';
  saving = false;
  statusMessage = ''; // 底部状态栏消息

  // ── 脏检测状态 ──────────────────────────────────────────
  private initialSnapshot: string = ''; // 初始配置快照
  private testRequestSeq = 0;

  ngOnInit(): void {
    this.loadConfig();
    this.captureInitialSnapshot();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['visible'] && !changes['visible'].currentValue) {
      this.resetTransientState();
    }

    this.loadConfig();
    if (changes['visible']?.currentValue && !changes['visible']?.previousValue) {
      this.resetTransientState();
      this.captureInitialSnapshot();
    }
  }

  ngAfterViewChecked(): void {
    // 在视图更新后按当前 editing 项精确聚焦输入框，避免多个模板引用时焦点落错
    if (this.needFocusProfileInput && this.editingProfileId) {
      const inputRef = this.profileRenameInputs?.find(
        item => item.nativeElement.dataset['profileRenameInput'] === this.editingProfileId,
      );
      if (inputRef) {
        inputRef.nativeElement.focus();
        inputRef.nativeElement.select();
        this.needFocusProfileInput = false;
      }
    }
    if (this.needFocusTemplateInput && this.editingTemplateId) {
      const inputRef = this.templateRenameInputs?.find(
        item => item.nativeElement.dataset['templateRenameInput'] === this.editingTemplateId,
      );
      if (inputRef) {
        inputRef.nativeElement.focus();
        inputRef.nativeElement.select();
        this.needFocusTemplateInput = false;
      }
    }
  }

  /**
   * 加载配置数据
   * 从父组件传入的 config 和 prompts 初始化本地状态
   */
  private loadConfig(): void {
    // 加载联通参数
    if (this.config?.runtime) {
      this.activeProfileId = this.config.runtime.activeProfileId || '';
      this.profiles = this.config.runtime.profiles || [];

      // 如果没有 profiles，创建默认配置
      if (this.profiles.length === 0) {
        this.profiles = [this.createDefaultProfile()];
        this.activeProfileId = this.profiles[0].id;
      }

      // 确保 activeProfileId 有效
      if (!this.profiles.find(p => p.id === this.activeProfileId)) {
        this.activeProfileId = this.profiles[0].id;
      }

      // 加载表单副本
      this.loadProfileForm();
    }

    // 加载提示词模板
    if (this.prompts) {
      this.activeTemplateId = this.prompts.activeTemplateId || '';
      this.templates = this.prompts.templates || [];

      // 如果没有 templates，创建默认模板
      if (this.templates.length === 0) {
        this.templates = [this.createDefaultTemplate()];
        this.activeTemplateId = this.templates[0].id;
      }

      // 确保 activeTemplateId 有效
      if (!this.templates.find(t => t.id === this.activeTemplateId)) {
        this.activeTemplateId = this.templates[0].id;
      }

      // 加载表单副本
      this.loadTemplateForm();
    }
  }

  // ══════════════════════════════════════════════════════════
  // 联通参数管理
  // ══════════════════════════════════════════════════════════

  /** 获取当前激活的 profile */
  get activeProfile(): Profile | null {
    return this.profiles.find(p => p.id === this.activeProfileId) || null;
  }

  /** 切换 profile */
  selectProfile(profileId: string): void {
    if (this.editingProfileId) return; // 正在编辑时不允许切换

    // 先把当前表单数据写回数组
    this.syncProfileFormToArray();

    // 切换激活项
    this.activeProfileId = profileId;
    this.testResult = ''; // 清空测试结果

    // 加载新的表单数据
    this.loadProfileForm();
  }

  /** 加载当前 profile 到表单副本 */
  private loadProfileForm(): void {
    const profile = this.activeProfile;
    if (profile) {
      this.profileFormData = { ...profile };
    } else {
      this.profileFormData = null;
    }
  }

  /** 将表单副本同步回数组
   * 注意：name 由页签重命名单独管理，不能被表单副本覆盖回旧值
   */
  private syncProfileFormToArray(): void {
    if (this.profileFormData && this.activeProfileId) {
      const profile = this.profiles.find(p => p.id === this.activeProfileId);
      if (profile) {
        const oldFingerprint = this.buildCapabilityFingerprint(profile);

        profile.baseUrl = this.profileFormData.baseUrl;
        profile.apiPath = this.profileFormData.apiPath;
        profile.apiKey = this.profileFormData.apiKey;
        profile.model = this.profileFormData.model;
        profile.timeout = this.profileFormData.timeout;
        profile.imageSize = this.profileFormData.imageSize;

        const newFingerprint = this.buildCapabilityFingerprint(profile);
        if (oldFingerprint !== newFingerprint && profile.imageSizeDetectionStatus === 'supported') {
          profile.imageSizeSupported = null;
          profile.imageSizeDetectionStatus = 'stale';
        }
      }
    }
  }

  /** 构建能力检测指纹 */
  private buildCapabilityFingerprint(profile: Profile): string {
    return `${profile.baseUrl}|${profile.apiPath}|${profile.apiKey}|${profile.model}`;
  }

  /** 判断 imageSize 是否可选 */
  get isImageSizeSelectable(): boolean {
    if (!this.profileFormData) return false;
    const currentFingerprint = this.buildCapabilityFingerprint(this.profileFormData);
    return (
      this.profileFormData.imageSizeSupported === true &&
      this.profileFormData.imageSizeDetectionStatus === 'supported' &&
      this.profileFormData.imageSizeDetectionFingerprint === currentFingerprint
    );
  }

  /** 新增 profile */
  addProfile(): void {
    // 先保存当前表单
    this.syncProfileFormToArray();

    const newProfile: Profile = {
      id: `profile_${Date.now()}`,
      name: `新方案 ${this.profiles.length + 1}`,
      baseUrl: 'https://api.302.ai',
      apiPath: '/google/v1/models/{model}',
      apiKey: '',
      model: 'gemini-2.5-flash-image',
      timeout: 240,
      imageSize: '2K',
      imageSizeSupported: null,
      imageSizeDetectionStatus: 'unknown',
      imageSizeDetectionFingerprint: null,
    };
    this.profiles.push(newProfile);
    this.activeProfileId = newProfile.id;
    this.statusMessage = '';

    // 加载新方案到表单
    this.loadProfileForm();
  }

  /** 开始重命名 profile */
  startRenameProfile(profileId: string, event: Event): void {
    event.stopPropagation();
    const profile = this.profiles.find(p => p.id === profileId);
    if (!profile) return;
    this.editingProfileId = profileId;
    this.editingProfileName = profile.name;
    this.needFocusProfileInput = true; // 标记需要聚焦

    // 强制在下一帧聚焦，确保 DOM 已更新
    setTimeout(() => {
      const inputRef = this.profileRenameInputs?.find(
        item => item.nativeElement.dataset['profileRenameInput'] === profileId,
      );
      if (inputRef) {
        inputRef.nativeElement.focus();
        inputRef.nativeElement.select();
      }
    }, 0);
  }

  /** 确认重命名 profile */
  confirmRenameProfile(): void {
    if (!this.editingProfileId) return;
    const profile = this.profiles.find(p => p.id === this.editingProfileId);
    if (profile && this.editingProfileName.trim()) {
      profile.name = this.editingProfileName.trim();
    }
    this.editingProfileId = null;
    this.editingProfileName = '';
  }

  /** 取消重命名 profile */
  cancelRenameProfile(): void {
    this.editingProfileId = null;
    this.editingProfileName = '';
  }

  /** 删除 profile */
  deleteProfile(profileId: string, event: Event): void {
    event.stopPropagation();

    if (this.profiles.length <= 1) {
      this.statusMessage = '⚠️ 至少保留一个联通参数配置';
      return;
    }

    if (!confirm('确定删除该联通参数配置吗？')) {
      return;
    }

    const index = this.profiles.findIndex(p => p.id === profileId);
    if (index === -1) return;

    this.profiles.splice(index, 1);

    if (this.activeProfileId === profileId) {
      this.activeProfileId = this.profiles[Math.max(0, index - 1)].id;
      this.loadProfileForm();
    }

    this.statusMessage = '';
  }

  /** 创建默认 profile */
  private createDefaultProfile(): Profile {
    return {
      id: 'profile_default',
      name: '默认配置',
      baseUrl: 'https://api.302.ai',
      apiPath: '/google/v1/models/{model}',
      apiKey: '',
      model: 'gemini-2.5-flash-image',
      timeout: 240,
      imageSize: '2K',
      imageSizeSupported: null,
      imageSizeDetectionStatus: 'unknown',
      imageSizeDetectionFingerprint: null,
    };
  }

  // ══════════════════════════════════════════════════════════
  // 提示词模板管理
  // ══════════════════════════════════════════════════════════

  /** 获取当前激活的 template */
  get activeTemplate(): Template | null {
    return this.templates.find(t => t.id === this.activeTemplateId) || null;
  }

  /** 切换 template */
  selectTemplate(templateId: string): void {
    if (this.editingTemplateId) return; // 正在编辑时不允许切换

    // 先把当前表单数据写回数组
    this.syncTemplateFormToArray();

    // 切换激活项
    this.activeTemplateId = templateId;

    // 加载新的表单数据
    this.loadTemplateForm();
  }

  /** 加载当前 template 到表单副本 */
  private loadTemplateForm(): void {
    const template = this.activeTemplate;
    if (template) {
      this.templateFormData = { ...template, variables: template.variables ? [...template.variables] : [] };
    } else {
      this.templateFormData = null;
    }
  }

  /** 将表单副本同步回数组
   * 注意：name 由页签重命名单独管理，不能被表单副本覆盖回旧值
   */
  private syncTemplateFormToArray(): void {
    if (this.templateFormData && this.activeTemplateId) {
      const template = this.templates.find(t => t.id === this.activeTemplateId);
      if (template) {
        template.description = this.templateFormData.description;
        template.content = this.templateFormData.content;
        template.variables = this.templateFormData.variables ? [...this.templateFormData.variables] : [];
      }
    }
  }

  /** 新增 template */
  addTemplate(): void {
    // 先保存当前表单
    this.syncTemplateFormToArray();

    const newTemplate: Template = {
      id: `template_${Date.now()}`,
      name: `新模板 ${this.templates.length + 1}`,
      description: '自定义提示词模板',
      content: '请根据封面图和书名《{book_name}》生成书籍展开图。',
      variables: [
        { name: 'book_name', description: '书名（自动获取）' },
        { name: 'cover_image', description: '封面参考图（自动获取）' },
      ],
    };
    this.templates.push(newTemplate);
    this.activeTemplateId = newTemplate.id;
    this.statusMessage = '';

    // 加载新模板到表单
    this.loadTemplateForm();
  }

  /** 开始重命名 template */
  startRenameTemplate(templateId: string, event: Event): void {
    event.stopPropagation();
    const template = this.templates.find(t => t.id === templateId);
    if (!template) return;
    this.editingTemplateId = templateId;
    this.editingTemplateName = template.name;
    this.needFocusTemplateInput = true; // 标记需要聚焦

    // 强制在下一帧聚焦，确保 DOM 已更新
    setTimeout(() => {
      const inputRef = this.templateRenameInputs?.find(
        item => item.nativeElement.dataset['templateRenameInput'] === templateId,
      );
      if (inputRef) {
        inputRef.nativeElement.focus();
        inputRef.nativeElement.select();
      }
    }, 0);
  }

  /** 确认重命名 template */
  confirmRenameTemplate(): void {
    if (!this.editingTemplateId) return;
    const template = this.templates.find(t => t.id === this.editingTemplateId);
    if (template && this.editingTemplateName.trim()) {
      template.name = this.editingTemplateName.trim();
    }
    this.editingTemplateId = null;
    this.editingTemplateName = '';
  }

  /** 取消重命名 template */
  cancelRenameTemplate(): void {
    this.editingTemplateId = null;
    this.editingTemplateName = '';
  }

  /** 删除 template */
  deleteTemplate(templateId: string, event: Event): void {
    event.stopPropagation();

    // 至少保留一个
    if (this.templates.length <= 1) {
      this.statusMessage = '⚠️ 至少保留一个提示词模板';
      return;
    }

    if (!confirm('确定删除该提示词模板吗？')) {
      return;
    }

    const index = this.templates.findIndex(t => t.id === templateId);
    if (index === -1) return;

    this.templates.splice(index, 1);

    // 如果删除的是当前激活项，切换到相邻项
    if (this.activeTemplateId === templateId) {
      this.activeTemplateId = this.templates[Math.max(0, index - 1)].id;
    }

    this.statusMessage = '';
  }

  /** 创建默认 template */
  private createDefaultTemplate(): Template {
    return {
      id: 'template_default',
      name: '默认模板',
      description: '标准印刷展开图',
      content: '请根据封面图和书名《{book_name}》生成书籍展开图。',
      variables: [
        { name: 'book_name', description: '书名（自动获取）' },
        { name: 'cover_image', description: '封面参考图（自动获取）' },
      ],
    };
  }

  /** 创建用于脏检测的配置快照 */
  private buildSnapshot(): string {
    this.confirmRenameProfile();
    this.confirmRenameTemplate();
    this.syncProfileFormToArray();
    this.syncTemplateFormToArray();

    return JSON.stringify({
      activeProfileId: this.activeProfileId,
      profiles: this.profiles,
      activeTemplateId: this.activeTemplateId,
      templates: this.templates,
    });
  }

  /** 记录弹窗打开时的初始状态 */
  private captureInitialSnapshot(): void {
    this.initialSnapshot = this.buildSnapshot();
  }

  /** 是否存在未保存修改 */
  private hasUnsavedChanges(): boolean {
    return this.buildSnapshot() !== this.initialSnapshot;
  }

  /** 重置瞬态 UI 状态 */
  private resetTransientState(): void {
    this.testing = false;
    this.testResult = '';
    this.saving = false;
    this.statusMessage = '';
    this.editingProfileId = null;
    this.editingProfileName = '';
    this.editingTemplateId = null;
    this.editingTemplateName = '';
    this.needFocusProfileInput = false;
    this.needFocusTemplateInput = false;
    this.testRequestSeq++;
  }

  /** 在模板中安全显示变量名，避免 HTML 里直接写花括号触发 Angular ICU 解析 */
  getVariableToken(name: string): string {
    return `{${name}}`;
  }

  // ══════════════════════════════════════════════════════════
  // 测试连接
  // ══════════════════════════════════════════════════════════

  testConnection(): void {
    // 先同步表单到数组
    this.syncProfileFormToArray();

    const profile = this.activeProfile;
    if (!profile) {
      this.testResult = '❌ 未选择联通参数配置';
      return;
    }

    if (!profile.baseUrl || !profile.apiPath || !profile.apiKey || !profile.model) {
      this.testResult = '❌ 请填写完整的联通参数';
      return;
    }

    this.testing = true;
    this.testResult = '测试中...';
    this.statusMessage = '';

    const currentSeq = ++this.testRequestSeq;

    // 通过父组件调用服务
    this.save.emit({
      action: 'test',
      payload: {
        activeProfileId: this.activeProfileId,
        profiles: this.profiles,
      },
      callback: (result: any) => {
        if (currentSeq !== this.testRequestSeq) return;

        this.testing = false;
        if (result.success) {
          this.testResult = '✅ 连接测试成功';

          const capabilities = result.capabilities || {};
          const imageSizeSupported = capabilities.imageSize === true;
          const detectionFingerprint = result.detectionFingerprint || null;

          if (this.profileFormData) {
            this.profileFormData.imageSizeSupported = imageSizeSupported;
            this.profileFormData.imageSizeDetectionStatus = imageSizeSupported ? 'supported' : 'unsupported';
            this.profileFormData.imageSizeDetectionFingerprint = detectionFingerprint;
          }

          const profile = this.profiles.find(p => p.id === this.activeProfileId);
          if (profile) {
            profile.imageSizeSupported = imageSizeSupported;
            profile.imageSizeDetectionStatus = imageSizeSupported ? 'supported' : 'unsupported';
            profile.imageSizeDetectionFingerprint = detectionFingerprint;
          }

          if (imageSizeSupported) {
            this.testResult += '，当前模型支持 imageSize';
          } else {
            this.testResult += '，但当前模型/网关不支持 imageSize';
          }
        } else {
          // 根据错误类型显示不同提示
          const errorType = result.errorType || 'unknown';
          const errorMsg = result.error || '未知错误';

          switch (errorType) {
            case 'auth_failed':
              this.testResult = `🔒 ${errorMsg}`;
              break;
            case 'model_unavailable':
              this.testResult = `⚠️ ${errorMsg}`;
              break;
            case 'config_error':
              this.testResult = `❌ ${errorMsg}`;
              break;
            case 'timeout':
              this.testResult = `⏱️ ${errorMsg}`;
              break;
            case 'network_error':
              this.testResult = `🌐 ${errorMsg}`;
              break;
            default:
              this.testResult = `❌ ${errorMsg}`;
          }
        }
      },
    });
  }

  // ══════════════════════════════════════════════════════════
  // 保存配置
  // ══════════════════════════════════════════════════════════

  saveConfig(): void {
    // 先把任何正在进行的改名同步到数组，再同步表单
    this.confirmRenameProfile();
    this.confirmRenameTemplate();
    this.syncProfileFormToArray();
    this.syncTemplateFormToArray();

    // 校验当前激活的 profile
    const profile = this.activeProfile;
    if (!profile || !profile.baseUrl || !profile.apiPath || !profile.apiKey || !profile.model) {
      this.statusMessage = '❌ 请填写完整的联通参数';
      return;
    }

    // 校验当前激活的 template
    const template = this.activeTemplate;
    if (!template || !template.content.trim()) {
      this.statusMessage = '❌ 提示词模板内容不能为空';
      return;
    }

    this.saving = true;
    this.statusMessage = '保存中...';

    const runtimeConfig = {
      activeProfileId: this.activeProfileId,
      profiles: this.profiles,
    };

    const promptConfig = {
      activeTemplateId: this.activeTemplateId,
      templates: this.templates,
    };

    this.save.emit({
      action: 'save',
      runtime: runtimeConfig,
      prompts: promptConfig,
      callback: (success: boolean) => {
        this.saving = false;
        if (success) {
          this.statusMessage = '✅ 配置已保存';
          this.captureInitialSnapshot();
          this.close.emit();
        } else {
          this.statusMessage = '❌ 保存失败';
        }
      },
    });
  }

  // ══════════════════════════════════════════════════════════
  // 键盘事件处理
  // ══════════════════════════════════════════════════════════

  @HostListener('document:keydown.escape')
  onEscapeKey(): void {
    if (this.editingProfileId) {
      this.cancelRenameProfile();
    } else if (this.editingTemplateId) {
      this.cancelRenameTemplate();
    }
  }

  // ══════════════════════════════════════════════════════════
  // 关闭弹窗
  // ══════════════════════════════════════════════════════════

  onCancel(): void {
    if (this.hasUnsavedChanges() && !confirm('当前有未保存的 AI 配置修改，确定放弃并关闭吗？')) {
      return;
    }
    this.resetTransientState();
    this.close.emit();
  }
}
