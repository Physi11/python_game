# 图标资源目录

这个目录用来放**地图图标**的 PNG。放进来就能生效，不用改任何代码。

## 怎么替换

1. 准备一张 **24 × 24 像素、带透明通道的 PNG**（尺寸不符也能用，程序会自动缩放；
   但没有透明通道的话，图标会带一个白底方块）。
2. 按 `../icons.json` 里登记的路径放进来，例如：

   ```
   assets/icons/player.png              ← 玩家
   assets/icons/monster/goblin.png      ← 哥布林
   assets/icons/item/sword_iron.png     ← 铁剑
   assets/icons/object/stairs.png       ← 下行楼梯
   ```

3. 回到游戏按 **F12**（或菜单「查看 → 重载图标资源」），不用重启。

删掉某个 PNG，对应图标就自动回退成原来的字符（`@`、`g`、`/`、`↓` …）。

## 查找顺序

某个格子要画图标时，按下面的顺序找第一个存在的文件：

| 格子 | 查找顺序 |
|---|---|
| 玩家 | `player` |
| 怪物 | `monster.<种类>` → `monster` |
| 道具 | `item.<道具名>` → `item.<类别>` → `item` |
| 楼梯 / 门 | `stair` / `door` |

举例：地图上出现「符文长剑」时，先找 `item/sword_rune.png`，没有就用
`item/weapon.png`（所有武器共用），再没有就用 `item/_default.png`（所有道具共用），
最后都没有就画回字符 `/`。

所以**只想换一类东西**时，只画一张 `item/potion.png` 就能覆盖全部药水。

## 不支持换图的东西

**墙和地板故意不做成图片。** 它们承担着战争迷雾的三态显示（未探索 / 已探索 /
当前可见），现在只改一个填充色就能完成；换成图片后每层 1000 个格子都要切换贴图，
还要为迷雾再准备一套压暗版本，收益几乎为零。楼梯、门属于"物件"，所以支持。

## 完整键名清单

见 `../icons.json` 的 `entries` 字段，共 26 项：

- `player`
- `monster.slime` / `monster.rat` / `monster.goblin` / `monster.bat` /
  `monster.skeleton` / `monster.gargoyle` / `monster.demon_lord` / `monster`
- `item.potion_small` / `item.potion_large` / `item.sword_iron` / `item.sword_rune` /
  `item.blade_abyss` / `item.armor_leather` / `item.armor_chain` /
  `item.scroll_flare` / `item.scroll_teleport` / `item.scroll_bless`
- `item.potion` / `item.weapon` / `item.armor` / `item.scroll` / `item`
- `stair` / `door`

## 想从模板开始画

```bash
python tools/export_icon_slots.py
```

会把 26 个条目按当前字符与配色渲染成 24×24 的占位 PNG，放到本目录对应位置，
之后直接在这些文件上改画即可。想恢复原样就把生成的 PNG 删掉。
