import ldap

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend, ModelBackend


class PLNLDAPBackend(BaseBackend):
    LDAP_SERVER = "ldap://10.28.0.154"
    LDAP_BASE_DN = "dc=plnbatam,dc=com"
    LDAP_DOMAIN = "PLNBATAM"

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        original_username = username

        if username.lower().endswith("@plnbatam.com"):
            username = username[:-13]

        bind_username = f"{self.LDAP_DOMAIN}\\{username}"

        print(f"[LDAP DEBUG] original={original_username} normalized={username}")
        print(f"[LDAP DEBUG] binding as {bind_username}")

        conn = None

        try:
            conn = ldap.initialize(self.LDAP_SERVER)
            conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
            conn.set_option(ldap.OPT_REFERRALS, 0)

            # 1. Bind langsung sebagai user login
            conn.simple_bind_s(bind_username, password)

            # 2. Search atribut user setelah bind sukses
            search_filter = f"(sAMAccountName={username})"
            attrs = [
                "mail",
                "name",
                "sAMAccountName",
                "employeeID",
                "title",
                "department",
                "manager",
                "distinguishedName",
            ]

            result = conn.search_s(
                self.LDAP_BASE_DN,
                ldap.SCOPE_SUBTREE,
                search_filter,
                attrs,
            )

            if not result:
                print("[LDAP DEBUG] search result empty")
                return None

            dn, entry = result[0]

            def get_attr(name, default=""):
                value = entry.get(name)
                if not value:
                    return default
                raw = value[0]
                if isinstance(raw, bytes):
                    return raw.decode("utf-8", errors="ignore")
                return str(raw)

            email = get_attr("mail", f"{username.lower()}@plnbatam.com")
            full_name = get_attr("name", username)
            samaccountname = get_attr("sAMAccountName", username)
            employee_id = get_attr("employeeID", "")
            title = get_attr("title", "")
            department = get_attr("department", "")
            manager = get_attr("manager", "")

            print(f"[LDAP DEBUG] bind success, ldap user={samaccountname}, email={email}")

            User = get_user_model()

            # pakai username hasil AD
            user, created = User.objects.get_or_create(
                username=samaccountname,
                defaults={
                    "email": email,
                    "is_staff": True,
                    "is_active": True,
                },
            )

            # update data user lokal
            user.email = email
            user.is_staff = True
            user.is_active = True

            # isi first_name / last_name sederhana
            parts = full_name.split()
            if parts:
                user.first_name = parts[0]
                user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            user.save()

            # simpan atribut tambahan ke session kalau perlu
            if request is not None:
                request.session["ldap_name"] = full_name
                request.session["ldap_email"] = email
                request.session["ldap_employee_id"] = employee_id
                request.session["ldap_title"] = title
                request.session["ldap_department"] = department
                request.session["ldap_manager"] = manager
                request.session["ldap_dn"] = dn

            return user

        except ldap.INVALID_CREDENTIALS:
            print("[LDAP DEBUG] invalid credentials")
            return None
        except ldap.LDAPError as e:
            print(f"[LDAP DEBUG] LDAP error: {e}")
            return None
        except Exception as e:
            print(f"[LDAP DEBUG] general error: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class SuperuserOnlyModelBackend(ModelBackend):
    """
    Fallback login lokal hanya untuk superuser.
    User biasa tidak boleh login dengan password lokal.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(
            request,
            username=username,
            password=password,
            **kwargs
        )
        if user and user.is_superuser:
            return user
        return None