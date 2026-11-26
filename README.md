# 巡展复制件配装台

馆员根据借展装箱单、展具清册和耗材清单编制校样。备件员按正式版交出实物，展台员看到交接明标后按实际底座选片。馆员班末按展次核对原交接及装撤事实。

## 启动与验证

使用 Python 3.11 标准库。从项目根目录运行以下命令。

```sh
python3 -B -m dispatch.site --db ./tour.sqlite3 init --sample
python3 -B -m dispatch.site --db ./tour.sqlite3 serve
python3 -B check_project.py
python3 -B -m dispatch.site demo
```

站点默认监听 `127.0.0.1:8000`。可给 `serve` 指定 `--port`。正式回归入口 `check_project.py` 由平台提供，直接运行原测试也可使用 `python3 -B -m unittest discover -s tests -t . -v`。演示使用独立临时库，核对真实业务回执后输出一条场景记录。原测试使用临时 SQLite 库和环回 HTTP。

## 一天的办理顺序

1. 在目录录入部件。复制件实物编号引用共享背标，实体底座编号引用共享槽标。可先装载样例。同库重复装载同一版本会保留现场改动。
2. 在校样页选部件，登记必配背标槽标对和各组禁配垫片。保存后可从当前修订填写后继稿。旧修订仍可查看和比较。
3. 看逐组试配。背板厚度加垫片厚度须落在槽深闭区间，禁配片排除。按垫片编号升序显示，单位均为整数毫米。背板 8 毫米、槽深 10 至 11 毫米时，1、2、3、4 毫米中的 2、3 合格。无候选的组留在校样待改。
4. 从校样签发。站点复核指定修订的全部组，保存当时采用的规格和计算清单。展次当前版切换后，旧正式号仍可领取。样例首稿为 `river-1`，展次为 `river`。
5. 在备件页按发行号和实物编号开单。用回执上的交接号进入展台。样例实物 `R1` 的背标为 `A`。
6. 展台录入实际底座编号，再从明标规则提供的垫片中选片。样例 `U1` 的槽标为 `u`。现场核验物件可用性及底座占用，垫片资格使用原发行清单。后改的厚度用于后续发行。
7. 从在展回执办理撤装，填写原因。旧回执保留实际实装和撤装，腾出的底座可供下一件使用。同一张交接只实装一次。
8. 在班末核对页按展次生成快照。未装、在展、已撤的网址通过核对号重领。现场后来改变时可办理新核对。

## HTTP 接口

浏览器用普通表单和 HTML 响应。JSON 请求提交 `Content-Type: application/json`。读 JSON 时使用 `Accept: application/json`。创建成功返回 201，目录更正和读请求成功返回 200。编号由 1 至 64 个 ASCII 字母、数字、点、下划线或连字符组成，首字符为字母或数字。站点产生的发行、交接、实装、撤装和核对号为正整数。

| 操作 | 路径与字段 |
| --- | --- |
| 录入复制件 | `POST /parts`，`kind=replica`，`id`，`back`，`thickness` |
| 录入底座 | `POST /parts`，`kind=base`，`id`，`slot`，`minimum`，`maximum` |
| 录入垫片 | `POST /parts`，`kind=pad`，`id`，`thickness` |
| 更正规格 | `POST /parts/revise`，同品类规格字段，`id` 为背标、槽标或垫片编号 |
| 可用状态 | `POST /parts/availability`，`kind`，实体或垫片 `id`，布尔值 `active`，表单填写 `true` 或 `false` |
| 保存与读取校样 | `POST /proofs`，见下例。`GET /proofs/{revision}`，`GET /proofs/{revision}/diff?against={older}` |
| 正式发行 | `POST /editions`，`revision`。`GET /editions/{id}`，`GET /editions/current?exhibition=river` |
| 开单和查单 | `POST /handoffs`，`edition_id`、`replica_id`。`GET /handoffs/{id}` |
| 实装 | `GET /mounts?handoff_id=1&base_id=U1` 领选项。`POST /mounts` 另提交 `pad_id` |
| 撤装 | `POST /removals`，`installation_id`、`reason` |
| 班末核对 | `POST /closeouts`，`exhibition`。`GET /closeouts/{id}` |

校样 JSON 示例与站内表单表达相同内容。表单内的部件编号用逗号分隔。每行一个组合，列为 `背标,槽标,禁配垫片,原因`，多个禁配垫片用 `|` 分隔。

```json
{
  "exhibition": "river",
  "revision": "river-2",
  "parent": "river-1",
  "replicas": ["R1", "R2", "R3"],
  "bases": ["U1", "U2"],
  "pads": ["X", "Y"],
  "groups": [{"back": "A", "slot": "u", "banned_pads": ["Y"], "reason": "本轮保持统一高度"}]
}
```

首稿的 `parent` 为 `null`。无效规格、无效目录引用和不完整字段返回 422。目录重号、编辑基线过期、整版覆盖不全、不可开单或安装、占用冲突和重复撤装返回 409。指定记录不存在返回 404。拒绝发行保留当前版，拒绝实装或撤装保留当时的实物与底座状态。读取历史不会推进现场状态。
