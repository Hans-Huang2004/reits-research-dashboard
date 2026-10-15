/* Shared field meaning and formatting for the project tables, details and exports. */
import { PUBLIC_FIELDS, INSTITUTIONAL_FIELDS } from './project-field-catalog.js?v=20261015-disclosures-1';
import { missingFieldText } from './field-evidence.js?v=20261015-disclosures-1';
export { PUBLIC_FIELDS, INSTITUTIONAL_FIELDS };

const exists = value => value !== null && value !== undefined && value !== '';
const scalar = value => exists(value) ? value : null;
const textValue = value => {
  if (!exists(value)) return '';
  if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join('；');
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}：${textValue(item)}`).join('；');
  return String(value);
};

export function getPublicField(record, key, context = {}) {
  const fund = context.fund || (context.isEvent ? null : record);
  switch (key) {
    case 'sequence': return scalar(context.sequence);
    case 'name': return scalar(record.name);
    case 'business_type': return scalar(record.business_type || (context.isEvent ? '' : '首发'));
    case 'exchange': return scalar(record.exchange);
    case 'product_type': return scalar(record.product_type || fund?.product_type);
    case 'issuer': return scalar(record.issuer); // Originator and issuer are distinct roles.
    case 'manager': return scalar(record.manager);
    case 'asset_type': return scalar(record.asset_type);
    case 'underlying_assets': return scalar(record.underlying_assets);
    case 'project_status': return scalar(record.stage || record.official_status);
    case 'updated_date': return scalar(record.updated_date);
    case 'sale_amount_cny_100m': {
      if (exists(record.sale_amount_cny_100m)) return record.sale_amount_cny_100m;
      if (!context.isEvent) return scalar(record.initial_raise_cny_100m);
      if (record.business_type === '首发' && ['已上市', '成立待上市'].includes(fund?.stage)) return scalar(fund.initial_raise_cny_100m);
      return null; // Never attach the fund's first offering amount to an expansion.
    }
    default: return scalar(record[key]);
  }
}

export function getInstitutionalField(record, key, context = {}) {
  switch (key) {
    case 'sequence': return scalar(context.sequence);
    case 'name': return scalar(record.name);
    case 'status': return typeof context.statusLabel === 'function' ? context.statusLabel(record.status) : scalar(context.statusLabel || record.official_status || record.status);
    case 'exchange': return scalar(record.ex || record.exchange);
    case 'declared_amount_cny_100m': return exists(record.declared_amount_cny_100m) ? record.declared_amount_cny_100m : scalar(record.amt);
    case 'asset_type': return scalar(record.research_field_sources?.asset_type?.length && record.asset_type ? record.asset_type : context.classification?.psub || record.psub || record.asset_type);
    case 'underlying_assets': return scalar(record.underlying_assets);
    case 'origin': return scalar(record.origin);
    case 'manager': return scalar(record.writer || record.mgr || record.manager);
    case 'accepted_date': return scalar(record.accepted_date || record.acc);
    case 'approved_date': return scalar(record.approved_date);
    case 'issued_date': return scalar(record.issued_date);
    case 'is_issued': return typeof record.is_issued === 'boolean' ? record.is_issued : null;
    default: return scalar(record[key]);
  }
}

export function formatProjectField(value, spec = {}) {
  if (!exists(value) || (Array.isArray(value) && !value.length)) return spec.type === 'boolean' ? '待核实' : '待补充';
  if (spec.type === 'boolean') return value === true ? '是' : value === false ? '否' : '待核实';
  if (spec.type === 'amount' || spec.type === 'integer') {
    const number = typeof value === 'number' ? value : Number(String(value).replaceAll(',', ''));
    return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: spec.type === 'integer' ? 0 : 4 }) : textValue(value);
  }
  if (spec.type === 'date') return textValue(value).slice(0, 10);
  return textValue(value);
}

export function projectFieldCellText(record, spec, context = {}) {
  const value = context.population === 'institutional' || INSTITUTIONAL_FIELDS.includes(spec) ? getInstitutionalField(record, spec.key, context) : getPublicField(record, spec.key, context);
  if (!exists(value) || (Array.isArray(value) && !value.length)) return missingFieldText(record, spec.key, spec.type === 'boolean' ? '待核实' : '待补充');
  return formatProjectField(value, spec);
}
