import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: '管理员',
    // 空字符串代表平台管理视图；选定用户组后，数据集市页只展示该组可访问的主题域。
    userGroup: '',
    shiftLabel: '白班 08:00-20:00',
    scope: '数据分析实验与数据应用服务平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isReadOnly: (state) => ['只读', '只读用户', 'readonly', 'viewer'].includes(state.role),
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setRole(role: string) {
      this.role = role
    },
    setUserGroup(group: string) {
      this.userGroup = group
    },
  },
})
