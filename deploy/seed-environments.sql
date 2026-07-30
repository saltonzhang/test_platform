START TRANSACTION;

INSERT INTO `test_aibetauto`.`aibet_environment` (`id`, `name`, `description`, `base_url`, `login_url`, `variables`, `is_default`, `created_at`, `updated_at`) VALUES
  (1, '前端测试环境', '日常开发联调与功能验证', 'https://api-test.helix.city', 'https://api-test.helix.city/api/v1/auth/login', '[{"key": "identifier", "value": "用户名"}, {"key": "password", "value": "密码"}]', 1, '2026-07-21 11:27:15.748936', '2026-07-24 02:52:43.956955'),
  (2, '预发布环境', '版本发布前的完整回归验证', 'https://api-stage.aibet.cn', '', '[{"key": "identifier", "value": "用户名"}, {"key": "password", "value": "密码"}]', 0, '2026-07-21 11:27:15.758541', '2026-07-24 02:49:23.559545'),
  (3, '生产环境', '线上服务可用性巡检', 'https://api.aibet.cn', '', '[]', 0, '2026-07-21 11:27:15.767512', '2026-07-21 11:27:15.767534'),
  (4, '后台测试环境', '日常开发和调试', 'http://mgt-api-test.helix.city', 'http://mgt-api-test.helix.city/api/v2/login', '[{"key": "userName", "value": "用户名"}, {"key": "password", "value": "密码"}]', 0, '2026-07-23 08:26:01.287313', '2026-07-27 09:46:45.145451');

COMMIT;
