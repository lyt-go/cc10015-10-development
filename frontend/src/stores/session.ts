import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '多维分析实验平台',
    // 当前操作者持有的实验归属范围；后端按此判定越权，空数组视为平台管理员。
    operatorScopes: ['scope-a', 'scope-b'] as string[],
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    scopeHeader: (state) => state.operatorScopes.join(','),
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setOperatorScopes(scopes: string[]) {
      this.operatorScopes = [...scopes]
    },
  },
})
