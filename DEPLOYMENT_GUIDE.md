# 🚀 Railway Deployment Guide

Production deployment of mAIrble Backend API using industry best practices.

## 📋 Prerequisites

1. **GitHub Account** (free)
2. **Railway Account** (free tier available)
3. **Your API Keys Ready**

## 🎯 Step 1: Push to GitHub

### Option A: Create New Repository
```bash
cd mairble-app/backend
git init
git add .
git commit -m "Initial commit: FastAPI backend ready for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mairble-backend.git
git push -u origin main
```

### Option B: Use Existing Repository
```bash
cd mairble-app/backend
git add .
git commit -m "Backend ready for Railway deployment"
git push
```

## 🚂 Step 2: Deploy to Railway

### 2.1 Create Railway Account
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub (recommended)
3. Connect your GitHub account

### 2.2 Create New Project
1. Click **"New Project"**
2. Select **"Deploy from GitHub repo"**
3. Choose your repository
4. Select the `backend` folder (if needed)
5. Railway will auto-detect FastAPI and start deployment

### 2.3 Configure Environment Variables
In Railway dashboard → **Variables** tab, add:

```
ENVIRONMENT=production
PRICELABS_API_KEY=your_actual_pricelabs_api_key_here
OPENAI_API_KEY=your_actual_openai_api_key_here
LISTING_ID=21f49919-2f73-4b9e-88c1-f460a316a5bc
PMS=yourporter
```

## ✅ Step 3: Verify Deployment

### 3.1 Check Health Endpoint
Once deployed, Railway will give you a URL like:
`https://your-app-name.up.railway.app`

Test it:
```bash
curl https://your-app-name.up.railway.app/
```

Should return:
```json
{
  "status": "healthy",
  "message": "mAIrble Backend API is running!",
  "version": "1.0.0",
  "environment": "production"
}
```

### 3.2 Test API Endpoints
```bash
# Test pricing data
curl -X POST "https://your-app-name.up.railway.app/fetch-pricing-data" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "your_pricelabs_api_key",
    "listing_id": "21f49919-2f73-4b9e-88c1-f460a316a5bc",
    "pms": "yourporter"
  }'
```

## 📱 Step 4: Update React Native App

Update `mairble-app/services/api.ts`:

```typescript
const POSSIBLE_BACKEND_URLS = [
  'https://your-app-name.up.railway.app',  // Production Railway URL
  'http://172.16.17.32:8000',              // Local development
  'http://127.0.0.1:8000',                 // Local fallback
];
```

## 🔒 Security Best Practices

✅ **Environment Variables**: API keys stored securely in Railway
✅ **HTTPS**: Automatic SSL certificates
✅ **CORS**: Configured for production
✅ **No Secrets in Code**: All sensitive data in environment variables
✅ **Proper Error Handling**: Production-safe error messages

## 📊 Monitoring & Logs

### View Logs
1. Railway Dashboard → Your Project
2. Click **"Deployments"** tab
3. View real-time logs and metrics

### Health Monitoring
- Railway automatically monitors your `/` endpoint
- Auto-restarts on failures
- Email notifications on downtime

## 🔄 Continuous Deployment

Railway automatically deploys when you push to GitHub:

```bash
# Make changes to your code
git add .
git commit -m "Update API endpoint"
git push

# Railway automatically deploys the new version!
```

## 💰 Pricing

- **Free Tier**: $5 credit per month (plenty for MVP)
- **Pro Plan**: $20/month (when you need more resources)
- **Pay-as-you-go**: Only pay for what you use

## 🆘 Troubleshooting

### Deployment Failed
1. Check Railway logs for error messages
2. Verify all files are committed and pushed
3. Ensure `requirements.txt` includes all dependencies

### Environment Variables Not Working
1. Double-check variable names in Railway dashboard
2. No quotes around values in Railway UI
3. Redeploy after adding variables

### Health Check Failing
1. Verify `/` endpoint returns `{"status": "healthy"}`
2. Check Railway logs for startup errors
3. Ensure `PORT` environment variable is used

## 🎉 Success!

Your FastAPI backend is now:
- ✅ **Deployed on Railway** with HTTPS
- ✅ **Globally accessible** from any device
- ✅ **Auto-scaling** based on demand
- ✅ **Continuously deployed** from GitHub
- ✅ **Production-ready** with proper security

**Next**: Update your React Native app to use the production URL! 