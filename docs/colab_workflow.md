# Colab + Git 工作流

## 首次建立 GitHub 仓库

仓库名建议 `archery-tag-balance`。可先设为 Private；公开与否由所有者决定。若上传本骨架，不要额外生成一个不同的 README。新建仓库后可用 GitHub 的 Upload files 上传，确保 `.gitignore` 和 `.gitattributes` 也被提交；GitHub 不会自动解压上传的 ZIP。

## 运行位置

Notebook 可由 GitHub 打开，也可上传至 Colab。代码在 `/content/archery-tag-balance` 工作，批量输出先写临时磁盘，再定期复制到 Drive。不要把大量逐帧文件直接写入挂载 Drive。

`00_setup.ipynb` 的克隆单元只处理无需凭据的仓库。私有仓库可先将已认证下载的项目 ZIP 上传并解压到 `/content/archery-tag-balance`，再运行配置检查；ZIP 没有 Git 历史，实验版本需另存下载时的 commit。需要私有仓库 Git 同步时再配置受限凭据，不能写入 notebook、仓库文件、remote URL 或日志。

## 版本保存

修改 `.py`、配置、文档后，需要明确 `git add`、`git commit`、`git push`。Notebook 的保存不会自动提交工作目录里的文件。推送前检查差异和输出是否包含凭据。不要在 Notebook 中使用带密码/token的仓库地址。

## 断开与恢复

在运行时回收前，将未推送代码打包备份至 Drive，并保存实验配置快照、进度、随机状态和检查点。重新连接后恢复代码版本和产物，再继续实验。当前尚无训练代码或检查点。

## 环境记录

初始 notebook 只用标准库，不安装 RL/GPU 依赖。实现仿真时再选定并验证依赖，记录安装版本。每次正式实验保留 Python、依赖、代码提交、未提交变更、配置、种子、策略和硬件信息；不能承诺不同硬件下逐位一致。
