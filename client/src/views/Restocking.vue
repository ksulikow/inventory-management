<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="successMessage" class="success-banner">{{ successMessage }}</div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div v-if="recommendations.length === 0" class="card">
        <p class="empty-state">{{ t('restocking.noRecommendations') }}</p>
      </div>

      <template v-else>
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
          </div>
          <div class="budget-control">
            <input
              type="range"
              min="0"
              :max="budgetMax"
              step="500"
              v-model.number="budget"
              class="budget-slider"
            />
            <span class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.title') }} ({{ recommendations.length }})</h3>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>{{ t('restocking.table.sku') }}</th>
                  <th>{{ t('restocking.table.itemName') }}</th>
                  <th>{{ t('restocking.table.category') }}</th>
                  <th>{{ t('restocking.table.trend') }}</th>
                  <th>{{ t('restocking.table.suggestedQuantity') }}</th>
                  <th>{{ t('restocking.table.unitCost') }}</th>
                  <th>{{ t('restocking.table.lineTotal') }}</th>
                  <th>{{ t('restocking.table.leadTime') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in recommendations"
                  :key="item.sku"
                  :class="{ excluded: !isIncluded(item) }"
                >
                  <td>
                    <input
                      type="checkbox"
                      :checked="isIncluded(item)"
                      @change="toggleOverride(item, $event.target.checked)"
                    />
                  </td>
                  <td><strong>{{ item.sku }}</strong></td>
                  <td>{{ item.item_name }}</td>
                  <td>{{ item.category }}</td>
                  <td>
                    <span :class="['badge', item.trend]">
                      {{ t(`trends.${item.trend}`) }}
                    </span>
                  </td>
                  <td>{{ item.suggested_quantity }}</td>
                  <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                  <td><strong>{{ currencySymbol }}{{ item.line_total.toLocaleString() }}</strong></td>
                  <td>{{ item.lead_time_days }} {{ t('common.days') }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="totals-footer">
            <div class="totals-row">
              <span>{{ t('restocking.totalCost') }}</span>
              <strong>{{ currencySymbol }}{{ totalCost.toLocaleString() }}</strong>
            </div>
            <div class="totals-row">
              <span>{{ t('restocking.remainingBudget') }}</span>
              <strong :class="{ 'over-budget': remainingBudget < 0 }">
                {{ currencySymbol }}{{ remainingBudget.toLocaleString() }}
              </strong>
            </div>
          </div>

          <div class="place-order-row">
            <button
              class="btn-primary"
              :disabled="includedItems.length === 0 || submitting"
              @click="placeOrder"
            >
              {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const recommendations = ref([])

    const submitting = ref(false)
    const submitError = ref(null)
    const successMessage = ref(null)

    // Manual per-sku overrides: sku -> boolean. Falls back to auto-selection when absent.
    const manualOverrides = ref({})

    const budgetMax = computed(() => {
      const total = recommendations.value.reduce((sum, item) => sum + item.line_total, 0)
      if (total <= 0) return 10000
      return Math.ceil(total / 1000) * 1000
    })

    const budget = ref(5000)

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        recommendations.value = await api.getRestockRecommendations()
        // Initialize budget to roughly half of the max whenever data (re)loads
        budget.value = Math.round(budgetMax.value / 2)
      } catch (err) {
        error.value = 'Failed to load restock recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    // Auto-selection: walk the priority-sorted list, keeping a running total, and
    // include items whose full suggested quantity still fits under budget. Keep
    // scanning past items that don't fit so cheaper lower-priority items can
    // still slot into remaining budget.
    const autoSelectedSkus = computed(() => {
      const selected = new Set()
      let runningTotal = 0
      for (const item of recommendations.value) {
        if (runningTotal + item.line_total <= budget.value) {
          selected.add(item.sku)
          runningTotal += item.line_total
        }
      }
      return selected
    })

    const isIncluded = (item) => {
      const override = manualOverrides.value[item.sku]
      if (override !== undefined) return override
      return autoSelectedSkus.value.has(item.sku)
    }

    const toggleOverride = (item, checked) => {
      manualOverrides.value = { ...manualOverrides.value, [item.sku]: checked }
    }

    const includedItems = computed(() => recommendations.value.filter(isIncluded))

    const totalCost = computed(() => includedItems.value.reduce((sum, item) => sum + item.line_total, 0))

    const remainingBudget = computed(() => budget.value - totalCost.value)

    const placeOrder = async () => {
      submitting.value = true
      submitError.value = null
      successMessage.value = null
      try {
        const items = includedItems.value.map(item => ({ sku: item.sku, quantity: item.suggested_quantity }))
        const order = await api.createRestockOrder(items)
        successMessage.value = t('restocking.orderSuccess', {
          orderNumber: order.order_number,
          leadTime: order.lead_time_days
        })

        const orderedSkus = new Set(items.map(i => i.sku))
        await loadRecommendations()

        // Clear overrides for skus no longer present in the fresh recommendations
        const stillPresent = new Set(recommendations.value.map(r => r.sku))
        const clearedOverrides = {}
        for (const [sku, value] of Object.entries(manualOverrides.value)) {
          if (stillPresent.has(sku) && !orderedSkus.has(sku)) {
            clearedOverrides[sku] = value
          }
        }
        manualOverrides.value = clearedOverrides
      } catch (err) {
        submitError.value = t('restocking.orderError') + ': ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      currencySymbol,
      loading,
      error,
      recommendations,
      submitting,
      submitError,
      successMessage,
      budgetMax,
      budget,
      isIncluded,
      toggleOverride,
      includedItems,
      totalCost,
      remainingBudget,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-control {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.budget-slider {
  flex: 1;
  max-width: 400px;
}

.budget-value {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 100px;
}

tbody tr.excluded {
  opacity: 0.45;
}

.totals-footer {
  display: flex;
  justify-content: flex-end;
  gap: 2.5rem;
  padding: 1rem 0.75rem 0.25rem;
  border-top: 1px solid #e2e8f0;
  margin-top: 0.5rem;
}

.totals-row {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.25rem;
  font-size: 0.875rem;
  color: #64748b;
}

.totals-row strong {
  font-size: 1.125rem;
  color: #0f172a;
}

.over-budget {
  color: #ef4444 !important;
}

.place-order-row {
  display: flex;
  justify-content: flex-end;
  padding-top: 1rem;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.empty-state {
  color: #64748b;
  text-align: center;
  padding: 1rem;
}
</style>
